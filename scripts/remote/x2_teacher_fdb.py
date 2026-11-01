"""Replay frozen FDB30 with two-frame X2 commits and unchanged SoulX rules."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from x2_teacher_frontend import X2TeacherFrontend
from nemotron_teacher_fdb import analyze as baseline_analyze, load_controller, rpc, warmup_controller
from x2_streaming_probe import digest, distribution, load_audio, write_json


def run_case(model, audio, case_id, path, output):
    import numpy as np
    import torch
    identity = rpc(path, 'create')['session_id']
    frontend = X2TeacherFrontend(model, case_id)
    stopped, arrived = threading.Event(), threading.Condition()
    state = {'end': 0, 'eof': False, 'error': None}
    ledger, buffer, base = [], np.empty(0, np.float32), 0
    back_size = model.config.infer_config.input.audio_back_size
    ahead_size = model.config.infer_config.input.audio_ahead_size
    started = time.monotonic()

    def feed():
        nonlocal buffer
        try:
            for start in range(0, len(audio), 1280):
                end = min(start + 1280, len(audio))
                if stopped.wait(max(0, started + end / 16000 - time.monotonic())):
                    return
                pcm = (np.clip(audio[start:end], -1, 1) * 32767).astype('<i2').tobytes()
                rpc(path, 'push', session_id=identity, audio=base64.b64encode(pcm).decode())
                with arrived:
                    buffer = np.concatenate((buffer, np.frombuffer(pcm, '<i2').astype(np.float32) / 32768))
                    state['end'] = end
                    if end - len(ledger) * 2560 > 12800:
                        raise RuntimeError('SoulX audio backlog exceeded 800ms')
                    arrived.notify_all()
            with arrived:
                state['eof'] = True
                arrived.notify_all()
        except Exception:
            with arrived:
                state['error'] = traceback.format_exc()
                arrived.notify_all()

    reader = threading.Thread(target=feed, daemon=True)
    reader.start()
    seq, pending, eof_partial = 0, [], None
    file = (output / f'{case_id}.frames.jsonl').open('x')
    try:
        while True:
            begin, end = seq * 2560, (seq + 1) * 2560
            required = end + max(ahead_size, 200)
            with arrived:
                while state['end'] < required and not state['eof'] and not state['error']:
                    arrived.wait(.05)
                if state['error']:
                    raise RuntimeError(state['error'])
                if state['end'] < required:
                    eof_partial = {'begin': begin, 'end': state['end'], 'reason': 'insufficient_native_window',
                                   'arrived_text': frontend.cursor.text}
                    break
                if state['end'] - begin > 12800:
                    raise RuntimeError('Teacher processing backlog exceeded 800ms')
                back_start = max(0, begin - back_size)
                back = np.pad(buffer[back_start-base:begin-base].copy(), (max(0, back_size-begin), 0))
                chunk, ahead = buffer[begin-base:end-base].copy(), buffer[end-base:end+ahead_size-base].copy()
            with torch.inference_mode():
                frontend.prepare_audio(back, chunk, ahead)
            while not pending:
                if state['error']:
                    raise RuntimeError(state['error'])
                batch = rpc(path, 'poll', session_id=identity, after=seq)
                pending.extend(batch['steps'])
                if not pending:
                    if time.monotonic() - started - end / 16000 > .8:
                        raise RuntimeError('X2 completion backlog exceeded 800ms')
                    stopped.wait(.002)
            step = pending.pop(0)
            if step['step_seq'] != seq+1 or step['main_audio_end_sample'] != end or step['eof_received']:
                raise ValueError('X2 teacher pair is out of order or observes EOF padding')
            if step['consumed_samples'] != end+200 or step['consumed_samples'] > state['end']:
                raise ValueError('X2 observed PCM differs from the calibrated frame boundary')
            observed = max(required, step['consumed_samples'])
            with torch.inference_mode():
                frame = frontend.process_step(step, chunk, back, ahead, end, observed)
            if not (step['decode_completed_at'] <= frame['controller_started_at'] <= frame['teacher_injected_at']
                    <= frame['state_resolved_at'] <= frame['published_at']):
                raise ValueError('X2 teacher publication order is invalid')
            backlog = (time.monotonic() - started - end / 16000) * 1000
            if backlog > 800:
                raise RuntimeError('Joint publication backlog exceeded 800ms')
            release = rpc(path, 'release', session_id=identity, step_seq=seq+1, published_at=frame['published_at'])
            frame.update(release, native_step=step, teacher_step_seq=seq+1,
                         pairing_mode='fixed_two_frames', asr_observation_ahead_ms=12.5,
                         buffer_depth=len(pending), buffer_overflow=0, backlog_ms=backlog,
                         observed_backlog_ms=backlog-(observed-end)/16)
            ledger.append(frame)
            file.write(json.dumps(frame, ensure_ascii=False) + '\n')
            file.flush()
            seq += 1
            with arrived:
                retain = max(0, end-back_size)
                buffer, base = buffer[retain-base:], retain
        reader.join(3)
        if reader.is_alive() or state['error']:
            raise RuntimeError(state['error'] or 'X2 ingress did not terminate')
        tail = {'committed_token_ids': frontend.teacher_ids, 'pending_text': '', 'pending_token_ids': [],
                'text_commit_index': len(frontend.teacher_ids), 'control_text': frontend.control_text}
        online = frontend.close()['text']
        rpc(path, 'push', session_id=identity, eof=True)
        deadline = time.monotonic()+10
        while True:
            batch = rpc(path, 'poll', session_id=identity, after=seq)
            if batch['ended']:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('X2 EOF diagnostics exceeded ten seconds')
            stopped.wait(.01)
        metrics = batch['metrics']
        return {'case_id': case_id, 'passed': True, 'online_text': online, 'drained_text': metrics['text'],
                'teacher_tail': tail, 'frames': len(ledger), 'real_samples': len(audio),
                'processed_samples': seq*2560, 'pending_real_samples': len(audio)-seq*2560,
                'x2_metrics': metrics, 'eof_partial': eof_partial, 'post_pause_extensions': 0,
                'pending_tail_frames': 0, 'tail_reencode_count': 0, 'tail_replace_tokens': 0,
                'text_commit_index': len(frontend.teacher_ids), 'text_injected_tokens': len(frontend.teacher_ids),
                'whole_turn_rerecognition_calls': 0, 'buffer_overflow_frames': 0,
                'audio_buffer_overflow': frontend.audio_overflow, 'pairing_mode': 'fixed_two_frames',
                'empty_text_frames': sum(f['text_injected_tokens']==0 for f in ledger),
                'canonical_frames': sum(f['canonical_token_match'] for f in ledger),
                'max_backlog_ms': max((f['backlog_ms'] for f in ledger), default=0),
                'state_counts': dict(Counter(f['state_token'] for f in ledger)),
                'elapsed_seconds': time.monotonic()-started}
    finally:
        stopped.set()
        reader.join(3)
        frontend.kv = None
        file.close()
        rpc(path, 'close', session_id=identity)
        if reader.is_alive():
            raise RuntimeError('X2 ingress thread did not terminate')


def run(args):
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.35, 0)
    manifest = json.loads(args.manifest.read_text())
    if len(manifest['samples']) != 30 or sum(s['duration_seconds'] for s in manifest['samples']) > 1200:
        raise ValueError('Expected frozen FDB30')
    samples = manifest['samples']
    if args.smoke:
        samples = [next(s for s in samples if s['task']==task)
                   for task in ('smooth_turn_taking','pause_handling','user_interruption')]
    args.output.mkdir(exist_ok=False)
    write_json(args.output/'input_manifest.json', dict(manifest,samples=samples))
    result = {'passed': False, 'cases': [], 'teacher_forcing': True, 'timing_mode': 'realtime',
              'pairing_mode': 'fixed_two_frames', 'source': 'x2_streaming_asr',
              'source_commit': __import__('os').environ.get('SOULX_SOURCE_COMMIT'),
              'manifest_sha256': digest(args.manifest), 'x2_revision': '4c8df16',
              'soulx_revision': '61701c4ab8193cc1ee2220d3848872ac6c720142'}
    try:
        controller, result['checkpoint_checks'] = load_controller(args)
        result['warmup'] = warmup_controller(controller, args.output)
        result['x2_warmup'] = json.loads((args.output.parent/'asr_ready.json').read_text())
        for sample in samples:
            try:
                audio,gain = load_audio(sample)
                record = run_case(controller,audio,sample['case_id'],args.socket,args.output)
                record['gain'] = gain
            except Exception as exc:
                record = {'case_id':sample['case_id'],'passed':False,'error':str(exc),
                          'traceback':traceback.format_exc()}
                traceback.print_exc()
            result['cases'].append(record)
            write_json(args.output/'progress.json',result)
            print(json.dumps(record,ensure_ascii=False),flush=True)
        result['passed'] = len(result['cases'])==len(samples) and all(r['passed'] for r in result['cases'])
    except Exception as exc:
        result.update(error=str(exc),traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        result['peak_allocated_mib'] = torch.cuda.max_memory_allocated()/2**20
        result['peak_reserved_mib'] = torch.cuda.max_memory_reserved()/2**20
        write_json(args.output/'result.json',result)
    raise SystemExit(0 if result['passed'] else 1)


def attribution(frames):
    changed = [f for f in frames if f['raw_token']!=f['state_token']]
    return {'frames':len(frames),'empty_run_length':distribution([f['empty_run_length'] for f in frames]),
            'chunk_rms':distribution([f['chunk_rms'] for f in frames]),
            'rule_applied':len(changed),'silent_rule_changes':sum(f['chunk_rms']<.001 for f in changed),
            'speech_rule_changes':sum(f['chunk_rms']>=.001 for f in changed)}


def analyze(args):
    import numpy as np
    baseline_analyze(args)
    result = json.loads((args.probe/'result.json').read_text())
    manifest = json.loads((args.probe/'input_manifest.json').read_text())
    frames = [json.loads(line) for p in args.probe.glob('*.frames.jsonl') for line in p.read_text().splitlines()]
    r6 = []
    for sample in manifest['samples']:
        path = args.baseline/'probe'/f"{sample['case_id']}.frames.jsonl"
        if not path.exists():
            continue
        audio,_ = load_audio(sample)
        audio = (np.clip(audio,-1,1)*32767).astype('<i2').astype(np.float32)/32768
        empty = 0
        for line in path.read_text().splitlines():
            f = json.loads(line)
            empty = empty+1 if not f['raw_delta_text'] else 0
            end = f['processed_until']
            f.update(empty_run_length=empty,chunk_rms=float(np.sqrt(np.mean(audio[end-2560:end].astype(np.float64)**2))))
            r6.append(f)
    cases = [c for c in result['cases'] if c['passed']]
    summary = {'x2':attribution(frames),'r6':attribution(r6),
        'main_publication_ms':distribution([f['backlog_ms'] for f in frames]),
        'observed_publication_ms':distribution([f['observed_backlog_ms'] for f in frames]),
        'r6_main_publication_ms':distribution([f['backlog_ms'] for f in r6]),
        'r6_observed_publication_ms':distribution([f['observed_backlog_ms'] for f in r6]),
        'canonical_frames':sum(f['canonical_token_match'] for f in frames),
        'post_pause_extensions':sum(f['post_pause_extension'] for f in frames),
        'x2_closed_groups':sum(f['x2_closed_groups'] for f in frames),
        'x2_rtf':distribution([c['x2_metrics']['x2_rtf'] for c in cases]),
        'passed_cases':len(cases),'requested_cases':len(manifest['samples'])}
    gpu = args.probe.parent/'gpu_memory_mib.txt'
    if gpu.exists():
        summary['joint_peak_gpu_mib'] = max(int(s.split()[1]) for s in gpu.read_text().splitlines())
    write_json(args.output/'x2_audit.json',summary)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command',required=True)
    execute = commands.add_parser('run')
    for name in ('manifest','assets','check-source','socket','output'):
        execute.add_argument('--'+name,type=Path,required=True)
    execute.add_argument('--smoke',action='store_true')
    inspect = commands.add_parser('analyze')
    for name in ('probe','output','baseline'):
        inspect.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    {'run':run,'analyze':analyze}[args.command](args)


if __name__ == '__main__':
    main()
