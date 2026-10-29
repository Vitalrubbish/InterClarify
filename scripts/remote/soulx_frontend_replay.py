"""Replay bounded development audio through real SoulX and Context consumers."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from shared_context import FrontendConsumer, SharedContext, STATE_IDS
from soulx_frontend import SoulXFrontend, SOULX_REVISION, SENSEVOICE_REVISION, UPSTREAM_SHA256
from sensevoice_transcript import SenseVoiceObservation


PROBE_SHA256 = 'd733a878fbb3393dac0349cfa1293e4fad9a8bd5ec1f58ce6adc019de4b94f32'
LOADER_SHA256 = 'da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901'


def prepare_manifest(root, target):
    import soundfile as sf
    audio = root.parent / 'interclarify-xturnix-fleurs/dataset/fleurs_en_us/audio/dev/786465049904960526.wav'
    if hashlib.sha256(audio.read_bytes()).hexdigest() != PROBE_SHA256:
        raise ValueError('Development audio digest differs')
    duration = sf.info(str(audio)).duration
    reference_path = audio.parents[2] / 'source/en_us/dev.tsv'
    rows = [row.split('\t') for row in reference_path.read_text().splitlines() if audio.name in row.split('\t')]
    if len(rows) != 1:
        raise ValueError('Development reference is missing or ambiguous')
    cases = [
        {'case_id': 'original_full', 'gain': 'original', 'seconds': duration, 'repeat': 1, 'tail_seconds': 0},
        {'case_id': 'calibrated_full', 'gain': 'rms_005_peak_09', 'seconds': duration, 'repeat': 1, 'tail_seconds': 1.6},
        {'case_id': 'calibrated_prefix', 'gain': 'rms_005_peak_09', 'seconds': 3.2, 'repeat': 1, 'tail_seconds': 0},
        {'case_id': 'calibrated_repeat', 'gain': 'rms_005_peak_09', 'seconds': duration, 'repeat': 2, 'tail_seconds': 1.6},
        {'case_id': 'silence', 'gain': 'none', 'seconds': 2, 'repeat': 1, 'tail_seconds': 0},
    ]
    extra = root / 'models/sensevoice-small/example/en.mp3'
    if extra.is_file():
        info = sf.info(str(extra))
        cases.append({'case_id': 'sensevoice_english', 'gain': 'rms_005_peak_09',
                      'seconds': min(10., info.duration), 'repeat': 1, 'tail_seconds': 1.6,
                      'audio_path': str(extra), 'audio_sha256': hashlib.sha256(extra.read_bytes()).hexdigest(),
                      'native_sample_rate': info.samplerate, 'source': 'frozen SenseVoiceSmall official example'})
    manifest = {'schema': 'soulx-frontend-development-audio-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'audio_path': str(audio), 'audio_sha256': PROBE_SHA256, 'reference_text': rows[0][2],
                'reference_source_sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                'source_revision': '70bb2e84b976b7e960aa89f1c648e09c59f894dd', 'cases': cases,
                'limits': {'gpu': 1, 'cpu': 4, 'ram_gib': 32, 'seconds': 1200,
                           'pcm_bytes': 4194304, 'audio_queue_ms': 800, 'output_bytes': 134217728},
                'scope': 'existing development recording, derived views, and optional bundled English example; not a benchmark'}
    with target.open('x') as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write('\n')


class CaseAudit:
    """Check independently retained source results against two actual readers."""

    def __init__(self, case_id, output):
        self.readers = [FrontendConsumer(case_id), FrontendConsumer(case_id)]
        self.source = {}
        self.events, self.reads = [], [0, 0]
        self.stream = (output / f'{case_id}.events.jsonl').open('x')
        self.audits = (output / f'{case_id}.source.jsonl').open('x')

    def audit(self, kind, event):
        self.source[event['event_id']] = event
        self.audits.write(json.dumps({'audit_kind': kind, **event}, ensure_ascii=False) + '\n')
        self.audits.flush()

    def consume(self, context):
        batches = [reader.consume(context) for reader in self.readers]
        if batches[0] != batches[1]:
            raise AssertionError('Independent consumers disagree')
        for index, batch in enumerate(batches):
            self.reads[index] += len(batch)
        by_id = {v['event_id']: v for v in self.events}
        for event in batches[0]:
            if event['kind'] in ('asr_observation', 'user_state'):
                source = self.source[event['event_id']]
                for key in ('raw_text', 'text', 'tags', 'character_map', 'token', 'token_id',
                            'raw_token', 'raw_token_id', 'accepted', 'basis', 'audio_spans'):
                    if key in source and source[key] != event[key]:
                        raise AssertionError(f'Context changed captured {key}')
            for dependency in event.get('depends_on', []):
                if dependency not in by_id or by_id[dependency]['event_seq'] >= event['event_seq']:
                    raise AssertionError('Event became visible before its dependency')
            if event['kind'] == 'asr_observation':
                if event['call_status'] != 'error' and event.get('model_result'):
                    raw = event['model_result'][0]['text']
                    if raw != event['raw_text']:
                        raise AssertionError('Raw generate result was changed before capture')
                    parsed = SenseVoiceObservation.parse(raw)
                    if any(parsed[key] != event[key] for key in ('text', 'tags', 'character_map')):
                        raise AssertionError('ASR source parsing is inconsistent')
                    for tag in event['tags']:
                        if raw[tag['start']:tag['end']] != tag['token']:
                            raise AssertionError('Tag character span differs from the raw source')
            if event['kind'] == 'user_transcript' and event['version']:
                old = next(v for v in reversed(self.events) if v['kind'] == 'user_transcript')
                if event['asr_version'] > old['asr_version']:
                    if old['text'][:event['replace_from']] + event['replacement'] != event['text']:
                        raise AssertionError('Published transcript patch cannot be reconstructed')
            if event['kind'] == 'user_state':
                control = by_id[event['basis']['control_event_id']]
                if control['event_seq'] != event['basis']['control_event_seq']:
                    raise AssertionError('State control sequence differs')
                if event['accepted'] and STATE_IDS.get(event['token']) != event['token_id']:
                    raise AssertionError('Accepted state token ID differs')
            self.events.append(event)
            by_id[event['event_id']] = event
            self.stream.write(json.dumps({'consumer_read_at': time.monotonic(), **event}, ensure_ascii=False) + '\n')
        self.stream.flush()

    def close(self):
        self.stream.close()
        self.audits.close()


def distribution(values):
    import numpy as np
    return {'count': len(values), 'p50_ms': float(np.percentile(values, 50)),
            'p95_ms': float(np.percentile(values, 95)), 'max_ms': max(values)} if values else {'count': 0}


def replay_case(model, samples, real_count, case, output):
    import numpy as np
    case_id = case['case_id']
    audit = CaseAudit(case_id, output)
    context = SharedContext()
    incoming, stop = queue.Queue(maxsize=10), threading.Event()
    failure, ingress, stopped = [], [], []
    frontend = None
    try:
        frontend = SoulXFrontend(model, context, session_id=case_id, turn_id='user-1',
                                 on_commit=audit.consume, audit=audit.audit,
                                 active_output=lambda: {'output_id': case_id + ':output', 'session_id': case_id, 'phase': 'preparing'},
                                 stop_output=lambda event, output_id: stopped.append({'event_id': event['event_id'], 'output_id': output_id, 'at': time.monotonic()}))
        started = time.monotonic()
        def feed():
            try:
                for offset in range(0, len(samples), 1280):
                    end = min(offset + 1280, len(samples))
                    if stop.wait(max(0, started + end / 16000 - time.monotonic())):
                        return
                    # Derived tail boundaries are aligned to packets by construction.
                    boundaries = sorted(set([offset, end] + ([real_count] if offset < real_count < end else [])))
                    for begin, finish in zip(boundaries, boundaries[1:]):
                        incoming.put_nowait({'audio': samples[begin:finish].copy(),
                                             'synthetic': begin >= real_count, 'arrived_at': time.monotonic(),
                                             'begin': begin, 'end': finish})
                incoming.put({'eof': True}, timeout=3)
            except Exception as exc:
                failure.append(f'{type(exc).__name__}: {exc}')
                stop.set()
        reader = threading.Thread(target=feed, daemon=True)
        reader.start()
        queue_peak_ms = 0
        try:
            while True:
                if failure:
                    raise RuntimeError(f'Audio ingress failed: {failure}')
                if time.monotonic() - started > 120:
                    raise TimeoutError('Audio case exceeded 120 seconds')
                item = incoming.get(timeout=5)
                if item.get('eof'):
                    break
                wait_ms = (time.monotonic() - item['arrived_at']) * 1000
                queue_peak_ms = max(queue_peak_ms, wait_ms)
                if wait_ms > 800:
                    raise RuntimeError('Pending audio exceeded the 800ms bound')
                before = time.monotonic()
                result = frontend.feed_audio(item['audio'], synthetic=item['synthetic'])
                ingress.append({'begin': item['begin'], 'end': item['end'], 'synthetic': item['synthetic'],
                                'queue_ms': wait_ms, 'processing_ms': (time.monotonic() - before) * 1000,
                                'native_result': result})
        finally:
            stop.set()
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError('Audio ingress thread failed to stop')
        before_close = context.get_user_turn(case_id, 'user-1')['transcript']['text']
        frontend.close_turn('runtime_audio_case_end')
        view = context.get_user_turn(case_id, 'user-1')
        assert view['transcript']['text'] == before_close
        assert all(reader.turns['user-1']['text'] == before_close for reader in audit.readers)
        states = [v for v in audit.events if v['kind'] == 'user_state']
        transcripts = [v for v in audit.events if v['kind'] == 'user_transcript' and v['status'] == 'open' and v['text']]
        observations = [v for v in audit.events if v['kind'] == 'asr_observation']
        accepted_completes = [v['event_seq'] for v in states if v['accepted'] and v['token'] == '<|user_complete|>']
        first_complete = min(accepted_completes, default=float('inf'))
        return {'case_id': case_id, 'passed': True, 'integrity_passed': True,
                'input_samples': len(samples), 'real_samples': real_count,
                'audio_ingress_sha256': hashlib.sha256(samples.tobytes()).hexdigest(),
                'closed_text': before_close, 'assembly_status': view['transcript'].get('assembly_status'),
                'source_calls': len(observations), 'source_errors': sum(v['call_status'] == 'error' for v in observations),
                'source_tags': dict(Counter(t['token'] for v in observations for t in v['tags'])),
                'state_counts': dict(Counter(v['token'] for v in states)),
                'accepted_state_counts': dict(Counter(v['token'] for v in states if v['accepted'])),
                'state_adjustments': sum(v['raw_token'] != v['token'] for v in states),
                'controller_resets': sum(v['kind'] == 'frontend_lifecycle' for v in audit.events),
                'text_versions': len(transcripts),
                'versions_before_complete': sum(v['event_seq'] < first_complete for v in transcripts),
                'unresolved_calls': sum(v['assembly_result'].get('assembly_status') == 'gap' for v in observations),
                'consumer_events': audit.reads, 'queue_peak_ms': queue_peak_ms,
                'postprocess_sha256': frontend.postprocess_sha256,
                'elapsed_seconds': time.monotonic() - started,
                'source_publication': distribution([(v['published_at'] - v['asr_returned_at']) * 1000 for v in observations]),
                'state_publication': distribution([(v['published_at'] - v['state_resolved_at']) * 1000 for v in states]),
                'stop_requests': stopped, 'ingress': ingress}
    finally:
        if frontend:
            if sys.exc_info()[0] is not None:
                frontend.detach(aborted=True)
            else:
                if not frontend.closed:
                    frontend.close_turn('runtime_audio_case_end')
                frontend.detach()
        audit.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--check-source', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepare-manifest', action='store_true')
    args = parser.parse_args()
    if args.prepare_manifest:
        prepare_manifest(args.root, args.manifest)
        return
    import numpy as np
    import soundfile as sf
    import torch
    manifest = json.loads(args.manifest.read_text())
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'manifest': manifest,
              'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'soulx_revision': SOULX_REVISION, 'sensevoice_revision': SENSEVOICE_REVISION,
              'upstream_sha256': UPSTREAM_SHA256, 'cases': [], 'passed': False,
              'source_commit': os.environ.get('SOULX_SOURCE_COMMIT'),
              'packages': {name: importlib.metadata.version(name) for name in ('torch', 'torchaudio', 'transformers', 'funasr', 'numpy')}}
    started = time.monotonic()
    args.output.mkdir(exist_ok=False)
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError('Exactly one scheduler-assigned GPU is required')
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        torch.cuda.set_per_process_memory_fraction(.83, 0)
        torch.manual_seed(42)
        loader_path = args.check_source / 'scripts/remote/check_component.py'
        if hashlib.sha256(loader_path.read_bytes()).hexdigest() != LOADER_SHA256:
            raise ValueError('Reusable loader digest differs')
        sys.path.insert(0, str(loader_path.parent))
        from check_component import load_soulx
        model, checks = load_soulx(args.root, args.root / 'upstream/frozen-20261028', args.output)
        result['checkpoint_checks'] = checks
        with torch.inference_mode():
            for _ in range(3):
                model.process(np.zeros(2560, dtype=np.float32))
        torch.cuda.synchronize()
        model.reset()
        path = Path(manifest['audio_path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['audio_sha256']:
            raise ValueError('Replay audio digest differs from frozen manifest')
        audio, sr = sf.read(path, dtype='float32')
        if sr != 16000 or audio.ndim != 1:
            raise ValueError('Frozen development audio must be mono 16kHz')
        rms, peak = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))), float(np.max(np.abs(audio)))
        gain = min(.05 / rms, .9 / peak)
        result['audio_calibration'] = {'source_rms': rms, 'source_peak': peak, 'gain': gain}
        with torch.inference_mode():
            for case in manifest['cases']:
                model.reset()
                case_audio, case_sr = audio, sr
                case_gain = gain
                if case.get('audio_path'):
                    import soxr
                    extra = Path(case['audio_path'])
                    if hashlib.sha256(extra.read_bytes()).hexdigest() != case['audio_sha256']:
                        raise ValueError('Additional audio source digest differs')
                    case_audio, case_sr = sf.read(extra, dtype='float32')
                    if case_audio.ndim > 1:
                        case_audio = case_audio.mean(axis=1)
                    if case_sr != 16000:
                        case_audio = soxr.resample(case_audio, case_sr, 16000)
                    case_sr = 16000
                    case_gain = min(.05 / float(np.sqrt(np.mean(case_audio.astype(np.float64) ** 2))),
                                    .9 / float(np.max(np.abs(case_audio))))
                if case['case_id'] == 'silence':
                    samples = np.zeros(int(case['seconds'] * sr), dtype=np.float32)
                else:
                    samples = np.tile(case_audio[:round(case['seconds'] * case_sr)], case['repeat'])
                    if case['gain'] != 'original':
                        samples = (samples * case_gain).astype(np.float32)
                real_count = len(samples)
                samples = np.concatenate([samples, np.zeros(round(case['tail_seconds'] * sr), dtype=np.float32)])
                try:
                    record = replay_case(model, samples, real_count, case, args.output)
                    record['applied_gain'] = case_gain if case['gain'] not in ('original', 'none') else 1.
                except Exception as exc:
                    record = {'case_id': case['case_id'], 'passed': False,
                              'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()}
                    result['cases'].append(record)
                    raise
                result['cases'].append(record)
                (args.output / 'progress.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                print(json.dumps({k: record[k] for k in ('case_id', 'passed', 'closed_text', 'state_counts', 'unresolved_calls')}, ensure_ascii=False), flush=True)
        result['passed'] = len(result['cases']) == len(manifest['cases']) and all(v['passed'] for v in result['cases'])
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        result['elapsed_seconds'] = time.monotonic() - started
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
