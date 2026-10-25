"""Exercise ASR-boundary scoring, sampling and arm-specific audio contracts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/training'))
sys.path.insert(0, str(ROOT / 'scripts/remote'))
from score_textturn_fdb import proportion, run, score_case
from freeze_textturn_fdb import freeze
from textturn_fdb_replay import load_audio


def trace(states, boundary=10., times=None):
    times = times or list(range(1, len(states)+1))
    events = [{'kind': 'context_publish', 'text': 'hello', 'published_at': boundary}]
    for index, (state, at) in enumerate(zip(states, times)):
        window = {'first_step_seq': index*3+1, 'last_step_seq': index*3+3,
                  'step_count': 3, 'partial_window': False, 'aggregation_wait_ms': 320}
        events += [{'kind': 'control_window', **window}, {'kind': 'control_result',
            'window': window, 'action': 'keep', 'state_after': state,
            'action_returned_at': at, 'state_recorded_at': at, 'control_ms': 50,
            'visible': {'state': state}}]
    events.append({'kind': 'case_end', 'runtime_success': True, 'control_calls': len(states),
                   'steps': 3*len(states), 'merged_windows': 0, 'eof_drain_events': 4})
    return events


CASE = {'case_id': 'test', 'subset': 'candor_turn_taking', 'sample_id': '1'}


class FdbContractTests(unittest.TestCase):
    def test_speak_is_separate_from_start_and_waits_use_return_time(self):
        events = trace(['Speak', 'Speak'], boundary=1.5)
        row = score_case(CASE, events)
        self.assertTrue(row['post_asr_speak'])
        self.assertFalse(row['post_asr_start'])
        self.assertIsNone(row['start_wait_beats'])
        events[4]['action'] = 'start'
        row = score_case(CASE, events)
        self.assertTrue(row['post_asr_start'])
        self.assertAlmostEqual(row['start_wait_beats'], .5/.48)
        # A repeated transcript and EOF transcript do not move the online boundary.
        events.insert(1, {'kind': 'context_publish', 'text': 'hello', 'published_at': 4.})
        events.insert(2, {'kind': 'asr_eof_drain', 'text': 'hello world', 'published_at': 5.})
        self.assertEqual(score_case(CASE, events)['t_last_asr_update'], 1.5)

    def test_three_cycle_rule_is_strict_and_listen_breaks_runs(self):
        for states, boundary, expected in [(['Speak']*2, 9, False), (['Speak']*3, 9, True),
                (['Speak']*3, 3, False), (['Speak']*4, 3.5, True),
                (['Speak', 'Listen', 'Speak', 'Speak'], 9, False)]:
            with self.subTest(states=states, boundary=boundary):
                row = score_case(CASE, trace(states, boundary))
                self.assertEqual(row['pre_asr_three_speak'], expected)

    def test_merged_cycle_is_one_observation_and_missing_trace_is_unknown(self):
        events = trace(['Speak']*3)
        events[4]['window'].update(step_count=6, last_step_seq=9)
        events[6]['window'].update(first_step_seq=10, last_step_seq=12)
        events.insert(1, {'kind': 'control_window', 'aggregation_wait_ms': 320})
        row = score_case(CASE, events)
        self.assertFalse(row['pre_asr_three_speak'])
        self.assertEqual(row['longest_pre_asr_speak'], 2)
        events.pop(1)
        self.assertIsNone(score_case(CASE, events)['post_asr_speak'])

    def test_missing_asr_failed_case_and_unknown_denominators(self):
        events = trace(['Listen'])
        events[0]['text'] = ''
        self.assertIsNone(score_case(CASE, events)['post_asr_start'])
        events = trace(['Speak'])
        events[-1]['runtime_success'] = False
        self.assertIsNone(score_case(CASE, events)['post_asr_speak'])
        metric = proportion([True, False, None])
        self.assertEqual((metric['hit'], metric['confirmed_miss'], metric['unknown']), (1, 1, 48))
        self.assertEqual(metric['decidable_denominator'], 2)
        self.assertEqual(metric['conservative_bounds'], [.02, .98])

    def test_ranked_freeze_audio_tail_and_no_sample_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = json.loads((ROOT / 'configs/textturn_fdb.json').read_text())
            config['per_arm'] = 2
            config_path = root / 'protocol.json'
            config_path.write_text(json.dumps(config))
            for arm, subset in enumerate(('candor_turn_taking', 'candor_pause_handling')):
                for index in range(4):
                    directory = root / subset / str(index)
                    directory.mkdir(parents=True)
                    sf.write(directory / 'input.wav', np.full(1600, .01*(index+1+arm*5)), 16000)
                    names = ['turn_taking.json'] if not arm else ['pause.json', 'transcription.json']
                    for name in names:
                        (directory / name).write_text(json.dumps([{'text': 'test', 'timestamp': [0, .08]}]))
            self.assertTrue(freeze(root, config_path, root/'freeze1'))
            self.assertTrue(freeze(root, config_path, root/'freeze2'))
            manifest = json.loads((root/'freeze1/manifest.json').read_text())
            self.assertEqual(manifest, json.loads((root/'freeze2/manifest.json').read_text()))
            for case in manifest['records']:
                audio, rate = load_audio(case, manifest)
                expected = 81600 if case['subset'] == 'candor_turn_taking' else 1600
                self.assertEqual(len(audio), expected)
                self.assertEqual(rate, 16000)
            bad = copy.deepcopy(manifest['records'][0])
            bad['files']['input.wav']['sha256'] = 'changed'
            with self.assertRaises(ValueError):
                load_audio(bad, manifest)
            config['candidate_sha256'] += '0'
            config_path.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                freeze(root, config_path, root/'invalid-hash')

    def test_absent_formal_run_preserves_all_one_hundred_unknowns(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = [{**CASE, 'case_id': f'{arm}-{i}', 'subset': arm} for arm in
                ('candor_turn_taking', 'candor_pause_handling') for i in range(50)]
            path = root/'manifest.json'
            path.write_text(json.dumps({'complete': True, 'records': records}))
            summary = run(path, root/'absent', root/'score')
            self.assertEqual(summary['turn_taking']['post_asr_start']['unknown'], 50)
            self.assertEqual(summary['pause_handling']['pre_asr_three_speak']['unknown'], 50)
            self.assertIsNone(summary['turn_taking']['start_wait_beats_mean'])


if __name__ == '__main__':
    unittest.main()
