"""Exercise data provenance, causal supervision and deterministic build recovery."""

import argparse
import copy
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'training'))
import layer1_data as data
import build_layer1_dataset as builder
import audit_layer1_dataset as auditor


class CharacterTokenizer:
    """Expose reversible IDs and source offsets without model dependencies."""

    def __init__(self, directory=None, expected=None):
        self.special = expected or CONFIG['token_ids']
        self.fingerprint = {'fixture': 'character-tokenizer-v1'}

    def encode(self, text):
        ids = []
        while text:
            match = next((m for m in self.special if text.startswith(m)), None)
            if match:
                ids.append(self.special[match])
                text = text[len(match):]
            else:
                ids.append(ord(text[0]) + 1)
                text = text[1:]
        return ids

    def decode(self, ids):
        reverse = {v: k for k, v in self.special.items()}
        return ''.join(reverse[i] if i in reverse else chr(i - 1) for i in ids)

    def user_chunks(self, text, rng, bounds):
        cursor = 0
        while cursor < len(text):
            stop = min(len(text), cursor + rng.randint(*bounds))
            yield {'text': text[cursor:stop], 'start': cursor, 'end': stop, 'base_tokens': stop - cursor}
            cursor = stop


CONFIG = yaml.safe_load((ROOT / 'configs/layer1_data.yaml').read_text())


class DataPipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(CONFIG)
        self.tokenizer = CharacterTokenizer()
        self.dialogue = {'dialogue_id': 'example', 'split': 'train', 'texts': [
            'Please explain the first subject, carefully.',
            'This is the old answer. Its final sentence must be discarded during interruption.',
            'Actually explain the other subject instead!',
            'Here is the new answer with its own explanation.']}

    def plan(self, **overrides):
        self.config['generation'].update(overrides)
        return data.MicroTurnPlanner(self.tokenizer, self.config).plan(self.dialogue, 0)

    def test_all_behaviors_and_interruption_abandons_tail(self):
        plan = self.plan(pause_probability=1, interruption_probability=1, backchannel_probability=1)
        events = plan['events']
        self.assertTrue({'natural_pause', 'user_continuation', 'response_start', 'interruption',
                         'user_backchannel', 'post_response_thinking'} <= {e['kind'] for e in events})
        interruption = next(i for i, e in enumerate(events) if e['control'] == 'interruption')
        old = ''.join(self.tokenizer.decode(e['assistant_ids']) for e in events[:interruption])
        self.assertTrue(self.dialogue['texts'][1].startswith(old))
        self.assertLess(len(old), len(self.dialogue['texts'][1]))
        following = ''.join(self.tokenizer.decode(e['assistant_ids']) for e in events[interruption:])
        self.assertEqual(following, self.dialogue['texts'][3])
        self.assertEqual(events[interruption]['assistant_ids'], [])
        for event in events:
            if event['kind'] == 'natural_pause':
                self.assertEqual(event['control'], 'speaking')
            if event['kind'] == 'user_backchannel':
                self.assertTrue(event['assistant_ids'])
                self.assertEqual(event['control'], 'backchannel')

    def test_single_chunk_interruption_has_separate_finish(self):
        self.dialogue['texts'][2] = 'No'
        plan = self.plan(interruption_probability=1)
        interruption = next(i for i, e in enumerate(plan['events']) if e['control'] == 'interruption')
        next_event = plan['events'][interruption + 1]
        self.assertEqual(next_event['control'], 'finish')
        self.assertEqual(next_event['user_text'], '')

    def test_delayed_start_targets_and_source_conservation(self):
        for single in (False, True):
            with self.subTest(single=single):
                self.dialogue['texts'] = ['Ask' if single else 'Please explain this subject.', 'An answer.']
                plan = self.plan(user_tokens=[3, 3], pause_probability=1)
                counts = auditor.audit_response_timing(plan, self.dialogue, self.tokenizer)
                self.assertEqual(counts['response_starts'], 1)
                events = plan['events']
                index = next(i for i, e in enumerate(events) if e['kind'] == 'response_start')
                self.assertEqual(events[index - 1]['kind'], 'user_final_wait')
                self.assertEqual(''.join(e['user_text'] for e in events if e['user_origin']),
                                 self.dialogue['texts'][0])
                encoder = data.SequenceEncoder(self.tokenizer, self.config, 220)
                for view in ('original', 'unpunctuated'):
                    _, wait = encoder.event_ids(events[index - 1], view)
                    prefix, start = encoder.event_ids(events[index], view)
                    self.assertEqual(wait, [CONFIG['token_ids']['<|user is talking|>'], encoder.eos])
                    self.assertEqual(prefix[len(encoder.user_header)], CONFIG['token_ids']['<|no voice|>'])
                    self.assertEqual(start, [CONFIG['token_ids']['<|user finish talking|>']]
                                     + events[index]['assistant_ids'] + [encoder.eos])

    def test_timing_audit_rejects_misalignment_and_duplicate_source(self):
        self.dialogue['texts'] = ['Please answer.', 'Certainly.']
        plan = self.plan()
        start = next(i for i, e in enumerate(plan['events']) if e['kind'] == 'response_start')
        for change in ('text_start', 'early_finish', 'duplicate', 'content'):
            broken = copy.deepcopy(plan)
            if change == 'text_start':
                broken['events'][start]['user_text'] = 'answer'
            elif change == 'early_finish':
                broken['events'][start - 1]['control'] = 'finish'
            elif change == 'content':
                broken['events'][start]['assistant_ids'] = [999]
            else:
                broken['events'].insert(start, copy.deepcopy(broken['events'][start - 1]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                auditor.audit_response_timing(broken, self.dialogue, self.tokenizer)

    def test_last_turn_never_fabricates_interruption(self):
        self.dialogue['texts'] = self.dialogue['texts'][:2]
        self.assertNotIn('interruption', [e['control'] for e in self.plan(interruption_probability=1)['events']])

    def test_seed_replay_and_epoch_variation(self):
        planner = data.MicroTurnPlanner(self.tokenizer, self.config)
        self.assertEqual(planner.plan(self.dialogue, 0), planner.plan(self.dialogue, 0))
        self.assertNotEqual(planner.plan(self.dialogue, 0), planner.plan(self.dialogue, 1))

    def test_punctuation_protects_words_numbers_and_specials(self):
        text = 'Don’t re-enter at 09:30; use 3.14, okay! <|no voice|>'
        self.assertEqual(data.remove_punctuation(text, self.config['views']['remove_characters']),
                         'Don’t re-enter at 09:30 use 3.14 okay <|no voice|>')

    def test_punctuation_only_boundaries_do_not_turn_into_no_voice(self):
        self.dialogue['texts'] = ['?Please answer.', 'Certainly.']
        plan = self.plan(user_tokens=[1, 1], interruption_probability=0)
        sourced = [e for e in plan['events'] if e['user_origin']]
        self.assertTrue(plan['sampling']['punctuation_boundary_merges'])
        self.assertEqual(''.join(e['user_text'] for e in sourced), self.dialogue['texts'][0])
        self.assertTrue(all(e['user_unpunctuated'].strip() for e in sourced))
        self.assertEqual(sourced[-1]['control'], 'speaking')
        encoder = data.SequenceEncoder(self.tokenizer, self.config, 4096)
        for event in sourced:
            prefix, _ = encoder.event_ids(event, 'unpunctuated')
            self.assertNotEqual(prefix[len(encoder.user_header)], self.config['token_ids']['<|no voice|>'])

    def test_punctuation_only_user_turn_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            index = data.DialogueIndex(Path(folder) / 'index.sqlite3', self.config)
            try:
                self.assertEqual(index.rejection({'id': 'punct', 'data': ['?!', 'This is an answer.']}),
                                 'empty_user_after_punctuation_removal')
            finally:
                index.close()

    def test_three_views_share_events_targets_and_supervise_once(self):
        plan = self.plan()
        encoder = data.SequenceEncoder(self.tokenizer, self.config, 220)
        results = [list(encoder.encode(plan, 'train', arm, view)) for arm, view in
                   [('T1', 'original'), ('T2', 'unpunctuated'), ('T3', 'original')]]
        targets = []
        for sequences in results:
            covered = []
            target_ids = []
            for row in sequences:
                self.assertLessEqual(len(row['input_ids']), 220)
                self.assertEqual(row['attention_mask'], [1] * len(row['input_ids']))
                for span in row['spans']:
                    self.assertTrue(all(x == -100 for x in row['labels'][span['start']:span['target_start']]))
                    if span['supervised']:
                        covered.append(span['event_id'])
                target_ids.extend(x for x in row['labels'] if x != -100)
            self.assertEqual(covered, list(range(len(plan['events']))))
            targets.append(target_ids)
        self.assertEqual(targets[0], targets[1])
        self.assertEqual(targets[0], targets[2])
        self.assertEqual([[s['event_id'] for s in r['spans']] for r in results[0]],
                         [[s['event_id'] for s in r['spans']] for r in results[1]])

    def test_numeric_protection_across_micro_turn_boundaries(self):
        self.dialogue['texts'] = ['Go at 09:30 and pay 3.14, please!', 'A sufficiently long answer.']
        plan = self.plan(user_tokens=[1, 1], pause_probability=0, interruption_probability=0)
        reconstructed = ''.join(e['user_unpunctuated'] for e in plan['events'] if e['user_origin'])
        self.assertEqual(reconstructed, 'Go at nine thirty and pay three point one four please')
        self.assertEqual(plan['user_turns']['0']['raw_text'], self.dialogue['texts'][0])
        self.assertEqual(''.join(self.tokenizer.decode(e['assistant_ids']) for e in plan['events']),
                         self.dialogue['texts'][1])

    def test_eval_views_frozen_across_training_epochs(self):
        rows = [{'dialogue_id': str(i), 'split': 'dev'} for i in range(10)]
        self.assertEqual(data.mixed_assignments(rows, 1, 0), data.mixed_assignments(rows, 1, 9))

    def test_never_exposes_future_user_input(self):
        plan = self.plan(interruption_probability=0)
        encoder = data.SequenceEncoder(self.tokenizer, self.config, 500)
        first = list(encoder.encode(plan, 'train', 'T1', 'original'))[0]
        self.assertNotIn('Actually explain', self.tokenizer.decode(first['input_ids']))

    def test_rejects_partial_event_instead_of_truncating(self):
        encoder = data.SequenceEncoder(self.tokenizer, self.config, 3)
        with self.assertRaisesRegex(ValueError, 'complete micro-turn'):
            list(encoder.encode(self.plan(), 'train', 'T1', 'original'))

    def test_mixed_assignment_no_duplicate_exposure(self):
        rows = [{'dialogue_id': str(i), 'split': 'train'} for i in range(1000)]
        assigned = data.mixed_assignments(rows, 123, 0)
        self.assertEqual(len(assigned), 1000)
        self.assertEqual(list(assigned.values()).count('original'), 500)
        self.assertNotEqual(assigned, data.mixed_assignments(rows, 123, 1))

    def test_exact_prefix_filter_has_threshold_pair_recall(self):
        universe = set(range(6))
        sets = [set(s) for n in range(1, 7) for s in itertools.combinations(universe, n)]
        for threshold in (0.5, 0.85, 1):
            for left in sets:
                for right in sets:
                    if len(left & right) >= threshold * len(left | right):
                        a = sorted(left)[:len(left) - data.math.ceil(threshold * len(left)) + 1]
                        b = sorted(right)[:len(right) - data.math.ceil(threshold * len(right)) + 1]
                        self.assertTrue(set(a) & set(b))

    def test_dedup_before_selection_and_exclusion_log(self):
        config = copy.deepcopy(self.config)
        config['splits'] = {'train': 2, 'dev': 1, 'test': 1}
        config['limits']['min_free_gib'] = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [{'id': 'a', 'data': [' '.join(f'word {i}' for i in range(80)), 'The original answer.']},
                    {'id': 'b', 'data': [' '.join(f'word {i}' for i in range(80)), 'The original answer!']},
                    {'id': 'c', 'data': ['A distinct query on botany and trees.', 'Plants grow using sunlight.']},
                    {'id': 'd', 'data': ['Another topic concerns airplane design.', 'Wings create sufficient lift.']},
                    {'id': 'e', 'data': ['Explain mineral chemistry and crystal structure.', 'Atoms form a lattice.']},
                    {'id': 'bad', 'data': ['<|user interruption|>', 'No marker injection allowed.']}]
            source = root / 'data.jsonl'
            source.write_text(''.join(data.canonical(row) + '\n' for row in rows))
            index = data.DialogueIndex(root / 'index.sqlite3', config)
            try:
                index.ingest([source], {'ids': [], 'normalized_hashes': []})
                selected = index.select()
                self.assertEqual(len(selected), 4)
                self.assertEqual(index.root('a'), index.root('b'))
                self.assertEqual(index.db.execute('SELECT reason FROM excluded').fetchone()[0], 'reserved_marker_or_encoding')
            finally:
                index.close()

    def test_spoken_number_forms_share_a_duplicate_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            index = data.DialogueIndex(Path(temporary) / 'index.sqlite3', self.config)
            try:
                for identity, text in [('digits', 'Please buy 42 apples.'), ('words', 'Please buy forty two apples.')]:
                    texts = [text, 'The fruit order is ready.']
                    index.index_candidate({'dialogue_id': identity, 'texts': texts,
                                           'normalized_sha256': data.digest(data.normalized(' '.join(texts)))})
                self.assertEqual(index.root('digits'), index.root('words'))
            finally:
                index.close()

    def test_candidate_sampling_scans_all_sources_and_is_order_independent(self):
        config = copy.deepcopy(self.config)
        config['splits'] = {'train': 2, 'dev': 1, 'test': 1}
        config['sampling'] = {'candidate_pool_dialogues': 6}
        config['limits']['min_free_gib'] = 0
        rows = [{'id': str(i), 'data': [f'Explain topic {i} with its own question.',
                                       f'Answer {i} provides a detailed explanation.']} for i in range(24)]
        expected = sorted((str(i) for i in range(24)), key=lambda x: (data.digest([config['seed'], x]), x))[:6]
        pools = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for run, items in enumerate((rows, list(reversed(rows)))):
                source = root / f'source{run}.jsonl'
                source.write_text(''.join(data.canonical(row) + '\n' for row in items))
                index = data.DialogueIndex(root / f'index{run}.sqlite3', config)
                try:
                    index.ingest([source], {'ids': [], 'normalized_hashes': []})
                    actual = [r[0] for r in index.db.execute('SELECT id FROM dialogues ORDER BY rank,id')]
                    self.assertEqual(actual, expected)
                    self.assertEqual(index.scan_summary['source_lines'], 24)
                    self.assertEqual(index.scan_summary['eligible_source_dialogues'], 24)
                    self.assertEqual(index.scan_summary['candidate_dialogues'], 6)
                    self.assertEqual(index.db.execute('SELECT COUNT(*) FROM source_inventory').fetchone()[0], 24)
                    pools.append(actual)
                finally:
                    index.close()
            self.assertEqual(pools[0], pools[1])

    def test_raw_window_sampling_is_bounded_reproducible_and_traceable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for shard in range(3):
                path = root / f'shard{shard}.jsonl'
                path.write_bytes(b''.join((data.canonical({'id': f'{shard}-{i}', 'data': ['A source question.',
                    'A source answer.']}) + '\n').encode() for i in range(100)))
                paths.append(path)
            first = list(data.source_records(paths, 123, 18))
            second = list(data.source_records(list(reversed(paths)), 123, 18))
            self.assertEqual(first, second)
            self.assertEqual(len(first), 18)
            self.assertEqual(len({(p.name, offset) for p, line, raw, offset in first}), 18)
            self.assertEqual({p.name for p, line, raw, offset in first}, {p.name for p in paths})
            self.assertTrue(all(line is None for p, line, raw, offset in first))
            for path, line, raw, offset in first:
                with path.open('rb') as stream:
                    stream.seek(offset)
                    self.assertEqual(stream.readline(), raw)
                self.assertIn('id', json.loads(raw))
            self.assertNotEqual(first, list(data.source_records(paths, 124, 18)))

    def test_raw_window_sampling_does_not_repeat_rows_to_fill_small_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'tiny.jsonl'
            path.write_bytes(b'{"id": "only", "data": ["Question", "Answer"]}\n')
            rows = list(data.source_records([path], 123, 6000))
            self.assertEqual(len(rows), 1)

    def make_build(self, root):
        config = copy.deepcopy(self.config)
        config['splits'] = {'train': 2, 'dev': 1, 'test': 1}
        config['limits']['min_free_gib'] = 0
        config_path = root / 'config.yaml'
        config_path.write_text(yaml.safe_dump(config))
        rows = [
            {'id': 'plants', 'data': ['Explain why green plants need sunshine.', 'Leaves convert sunlight into chemical energy.']},
            {'id': 'planes', 'data': ['How do commercial aircraft remain airborne?', 'Their wings generate aerodynamic lift.']},
            {'id': 'rocks', 'data': ['What causes mineral crystals to take shape?', 'Atoms arrange into a repeating lattice.']},
            {'id': 'music', 'data': ['Describe the rhythm of this musical genre.', 'It uses syncopated accents and layered percussion.']}]
        source = root / 'train.jsonl'
        source.write_text(''.join(data.canonical(row) + '\n' for row in rows))
        manifest = root / 'source.json'
        data.write_json(manifest, {**config['source'], 'files': [
            {'path': source.name, 'size': source.stat().st_size, 'lfs': {'oid': data.file_digest(source)}}]})
        download = root / 'download.json'
        data.write_json(download, {**config['source'], 'complete': True,
                                 'source_manifest_sha256': data.file_digest(manifest), 'files': [{'path': str(source)}]})
        exclusions = root / 'exclusions.json'
        data.write_json(exclusions, {'ids': [], 'normalized_hashes': [], 'source_refs': [], 'reviewed': False})
        return argparse.Namespace(config=config_path, source_manifest=manifest, source_dir=root,
                                  download_manifest=download, tokenizer=root, exclusions=exclusions,
                                  max_length=250, epoch=0, output=root / 'output', resume=False)

    def test_end_to_end_resume_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            with patch.object(builder, 'ReleasedTokenizer', CharacterTokenizer), patch.object(auditor, 'ReleasedTokenizer', CharacterTokenizer):
                built = builder.build(args)
                report = auditor.audit(args.output, args.tokenizer)
                self.assertTrue(report['machine_passed'])
                self.assertFalse(report['training_allowed'])
                self.assertFalse(report['minimum_32_human_review_passed'])
                self.assertIn('external_exclusion_review', report['pending'])
                self.assertEqual(report['source'], CONFIG['source'])
                self.assertTrue(all(r['rate'] is None or 0 <= r['rate'] <= 1 for r in report['observed_rates'].values()))
                first = copy.deepcopy(built['artifacts'])
                args.resume = True
                self.assertEqual(builder.build(args)['artifacts'], first)
                manifest_path = args.output / 'manifest.json'
                manifest = json.loads(manifest_path.read_text())
                manifest['complete'] = False
                manifest['next_dialogue'] = 1
                selected = json.loads((args.output / 'dialogues.json').read_text())
                first_key = 'dialogues/' + data.digest(selected[0]['dialogue_id']) + '.json'
                manifest['artifacts'] = {first_key: manifest['artifacts'][first_key]}
                data.write_json(manifest_path, manifest)
                self.assertEqual(builder.build(args)['artifacts'], first)
                artifact_path = args.output / next(iter(first))
                artifact = json.loads(artifact_path.read_text())
                artifact['sequences'][0]['labels'][0] = 1
                data.write_json(artifact_path, artifact)
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    auditor.audit(args.output, args.tokenizer)
                with self.assertRaisesRegex(ValueError, 'changed'):
                    builder.build(args)

    def test_source_tamper_and_incomplete_download_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            config = yaml.safe_load(args.config.read_text())
            args.source_dir.joinpath('train.jsonl').write_text('altered')
            with self.assertRaisesRegex(ValueError, 'Unverified source'):
                data.verify_sources(args.source_manifest, args.source_dir, args.download_manifest, config['source'])

    def test_incomplete_download_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            download = json.loads(args.download_manifest.read_text())
            download['complete'] = False
            data.write_json(args.download_manifest, download)
            config = yaml.safe_load(args.config.read_text())
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                data.verify_sources(args.source_manifest, args.source_dir, args.download_manifest, config['source'])
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            config = yaml.safe_load(args.config.read_text())
            config['filter']['min_chars'] = 10000
            args.config.write_text(yaml.safe_dump(config))
            with patch.object(builder, 'ReleasedTokenizer', CharacterTokenizer):
                with self.assertRaisesRegex(ValueError, 'Insufficient'):
                    builder.build(args)
                args.resume = True
                with self.assertRaisesRegex(ValueError, 'Interrupted source index'):
                    builder.build(args)

    def test_optional_fdb_text_coverage_does_not_add_training_data_review_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            data.write_json(args.exclusions, {'ids': [], 'normalized_hashes': [],
                'source_refs': ['fixture/external-evaluation'], 'reviewed': True,
                'review_scope': 'source_inventory_and_available_text', 'text_coverage_complete': False})
            with patch.object(builder, 'ReleasedTokenizer', CharacterTokenizer), patch.object(auditor, 'ReleasedTokenizer', CharacterTokenizer):
                builder.build(args)
                report = auditor.audit(args.output, args.tokenizer)
            self.assertTrue(report['exclusions_reviewed'])
            self.assertFalse(report['optional_text_coverage_complete'])
            self.assertNotIn('external_exclusion_review', report['pending'])
            self.assertIn('minimum_32_human_review', report['pending'])
            self.assertFalse(report['training_allowed'])

    def test_user_32_signoff_closes_data_issue_without_releasing_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            config = yaml.safe_load(args.config.read_text())
            config['splits'] = {'train': 32, 'dev': 0, 'test': 0}
            config['dedup']['jaccard_threshold'] = 1
            args.config.write_text(yaml.safe_dump(config))
            source = args.source_dir / 'train.jsonl'
            source.write_text(''.join(data.canonical({'id': str(i), 'data': [
                f'Question {i} on topic {data.digest(i)[:12].translate(str.maketrans("0123456789", "ghijklmnop"))}.', f'Answer for topic {i} is recorded here.']}) + '\n'
                for i in range(32)))
            pinned = json.loads(args.source_manifest.read_text())
            pinned['files'][0].update(size=source.stat().st_size, lfs={'oid': data.file_digest(source)})
            data.write_json(args.source_manifest, pinned)
            download = json.loads(args.download_manifest.read_text())
            download['source_manifest_sha256'] = data.file_digest(args.source_manifest)
            data.write_json(args.download_manifest, download)
            data.write_json(args.exclusions, {'ids': [], 'normalized_hashes': [], 'source_refs': ['fixture'], 'reviewed': True})
            with patch.object(builder, 'ReleasedTokenizer', CharacterTokenizer), patch.object(auditor, 'ReleasedTokenizer', CharacterTokenizer):
                builder.build(args)
                path = args.output / 'human_review.json'
                review = json.loads(path.read_text())
                review['policy'] = 'user_minimum_32_signoff'
                data.write_json(path, review)
                pending = auditor.audit(args.output, args.tokenizer)
                self.assertFalse(pending['parent_issue_complete'])
                self.assertNotIn('expanded_behavior_and_double_review', pending['pending'])
                for row in review['minimum_set']:
                    row.update(reviewer='fixture_user', accepted=True)
                data.write_json(path, review)
                passed = auditor.audit(args.output, args.tokenizer)
                self.assertTrue(passed['parent_issue_complete'])
                self.assertFalse(passed['training_allowed'])
                self.assertIn('issue005_resource_and_recovery', passed['pending'])
                review['minimum_set'][0]['sha256'] = 'changed'
                data.write_json(path, review)
                self.assertFalse(auditor.audit(args.output, args.tokenizer)['parent_issue_complete'])

    def test_rejects_unreviewed_claim_without_external_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            data.write_json(args.exclusions, {'ids': [], 'normalized_hashes': [], 'source_refs': [], 'reviewed': True})
            with self.assertRaisesRegex(ValueError, 'checked external sources'):
                builder.build(args)

    def test_explicit_user_waiver_closes_data_without_faking_signatures(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.make_build(Path(temporary))
            args.human_review_waiver_reason = 'User explicitly waived r5 human review.'
            data.write_json(args.exclusions, {'ids': [], 'normalized_hashes': [], 'source_refs': ['fixture'], 'reviewed': True})
            with patch.object(builder, 'ReleasedTokenizer', CharacterTokenizer), patch.object(auditor, 'ReleasedTokenizer', CharacterTokenizer):
                builder.build(args)
                report = auditor.audit(args.output, args.tokenizer)
                self.assertTrue(report['parent_issue_complete'])
                self.assertTrue(report['human_review_waived'])
                self.assertFalse(report['minimum_32_human_review_passed'])
                self.assertFalse(report['training_allowed'])
                self.assertNotIn('minimum_32_human_review', report['pending'])
                path = args.output / 'human_review.json'
                review = json.loads(path.read_text())
                self.assertTrue(all(r['accepted'] is None for r in review['minimum_set']))
                review['waiver_reason'] = 'changed'
                data.write_json(path, review)
                with self.assertRaisesRegex(ValueError, 'waiver'):
                    auditor.audit(args.output, args.tokenizer)

    def test_invalid_configuration_and_unicode_fail_closed(self):
        config = copy.deepcopy(self.config)
        config['generation']['backchannels'] = [True]
        with self.assertRaisesRegex(ValueError, 'plain nonempty strings'):
            data.validate_config(config)
        with tempfile.TemporaryDirectory() as temporary:
            index = data.DialogueIndex(Path(temporary) / 'index.sqlite3', self.config)
            try:
                self.assertEqual(index.rejection({'id': 'x', 'data': ['Unicode surrogate \ud800 in text', 'Answer text.']}),
                                 'invalid_unicode')
            finally:
                index.close()

    def test_actual_tokenizer_metadata_and_single_token_validation(self):
        from tokenizers import Tokenizer, models
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = {marker: i for i, marker in enumerate(CONFIG['token_ids'])}
            tokenizer = Tokenizer(models.WordLevel({**mapping, 'unknown': len(mapping)}, unk_token='unknown'))
            tokenizer.add_special_tokens(list(mapping))
            tokenizer.save(str(root / 'tokenizer.json'))
            data.write_json(root / 'tokenizer_config.json', {'bos_token': None, 'eos_token': '<|im_end|>'})
            loaded = data.ReleasedTokenizer(root, mapping)
            self.assertEqual(loaded.encode('<|no voice|>'), [mapping['<|no voice|>']])
            mapping['<|no voice|>'] = 1234
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                data.ReleasedTokenizer(root, mapping)


if __name__ == '__main__':
    unittest.main()
