"""Replay fixed FDB audio through independently scheduled SoulX and RNNT."""
import argparse
import base64
from collections import Counter
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).parents[1] / 'runtime'))
from dual_asr_frontend import DualASRFrontend, PairedPublisher
from shared_context import SharedContext
from nemotron_teacher_fdb import digest, write_json, rpc, analyze

MANIFEST_SHA256 = '403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07'


def load_controller(args):
    loader = args.check_source / 'scripts/remote/check_component.py'
    if digest(loader) != 'da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901':
        raise ValueError('Reusable SoulX loader digest differs')
    sys.path.insert(0, str(loader.parent))
    from check_component import load_soulx
    return load_soulx(args.assets, args.assets / 'upstream/frozen-20261028', args.output)


def run_case(model, audio, case_id, path, output, frontend_factory=DualASRFrontend):
    import numpy as np
    import torch
    model.reset()
    identity = rpc(path, 'create')['session_id']
    incoming, stop, ingress_done, soulx_done = queue.Queue(maxsize=10), threading.Event(), threading.Event(), threading.Event()
    guard = threading.Lock()
    progress = {'arrived': 0, 'soulx_observed': 0, 'errors': [], 'soulx_pcm': {},
                'peak_ingress_packets': 0, 'peak_soulx_unread': 0}
    counts, raw_counts = Counter(), Counter()
    frame_count, seq, started = 0, 0, time.monotonic()
    last_frame, batch, frontend, native_text = None, {}, None, ''
    streams = {kind: (output / f'{case_id}.{kind}.jsonl').open('x')
               for kind in ('frames', 'source', 'native', 'unpublished')}

    def write(kind, value):
        streams[kind].write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        streams[kind].flush()

    def failed():
        with guard:
            progress['errors'].append(traceback.format_exc())
        stop.set()

    def audit(kind, value):
        write('source', {'audit_kind': kind, **value})

    def committed(frame):
        nonlocal frame_count, last_frame
        frame['backlog_ms'] = (frame['published_at'] - started - frame['processed_until'] / 16000) * 1000
        frame['observed_backlog_ms'] = (frame['published_at'] - started - frame['audio_observed_until'] / 16000) * 1000
        frame['state_backlog_ms'] = (frame['state_resolved_at'] - started - frame['processed_until'] / 16000) * 1000
        frame_count += 1
        last_frame = frame
        counts[frame['state_token']] += 1
        raw_counts[frame['raw_token']] += 1
        write('frames', frame)
        if frame['backlog_ms'] > 800:
            raise RuntimeError('Paired publication backlog exceeded 800ms')

    context = SharedContext()
    publisher = PairedPublisher(context, case_id, on_commit=committed)

    def feed():
        try:
            for begin in range(0, len(audio), 1280):
                end = min(begin + 1280, len(audio))
                if stop.wait(max(0, started + end / 16000 - time.monotonic())):
                    return
                if time.monotonic() - started - end / 16000 > .8:
                    raise RuntimeError('Realtime audio ingress exceeded 800ms')
                pcm = (np.clip(audio[begin:end], -1, 1) * 32767).astype('<i2').tobytes()
                packet = np.frombuffer(pcm, '<i2').astype(np.float32) / 32768
                with guard:
                    progress['arrived'] = end
                    progress['soulx_observed'] = getattr(frontend, 'observed_input', 0)
                    unread = end - progress['soulx_observed']
                    progress['peak_soulx_unread'] = max(progress['peak_soulx_unread'], unread)
                    if unread > 12800:
                        raise RuntimeError('SoulX unread audio exceeded 800ms')
                incoming.put_nowait(packet)
                with guard:
                    progress['peak_ingress_packets'] = max(progress['peak_ingress_packets'], incoming.qsize())
                rpc(path, 'push', session_id=identity, audio=base64.b64encode(pcm).decode())
            rpc(path, 'push', session_id=identity, eof=True)
        except Exception:
            failed()
        finally:
            ingress_done.set()

    def control():
        try:
            with torch.inference_mode():
                while not stop.is_set():
                    try:
                        packet = incoming.get(timeout=.02)
                    except queue.Empty:
                        if ingress_done.is_set():
                            break
                        continue
                    frontend.feed_audio(packet)
                    metrics = frontend.pcm_metrics()
                    with guard:
                        progress['soulx_observed'] = frontend.observed_input if hasattr(frontend, 'observed_input') else 0
                        progress['soulx_pcm'] = metrics
        except Exception:
            failed()
        finally:
            soulx_done.set()

    reader = threading.Thread(target=feed, daemon=True)
    controller = threading.Thread(target=control, daemon=True)
    record = {'case_id': case_id, 'passed': False, 'real_samples': len(audio)}
    try:
        frontend = frontend_factory(model, publisher, audit=audit,
            active_output=lambda: {'output_id': case_id + ':probe', 'session_id': case_id, 'phase': 'preparing'},
            stop_output=lambda frame, output_id: audit('direct_stop', dict(frame, output_id=output_id, stopped_at=time.monotonic())))
        started = time.monotonic()
        reader.start()
        controller.start()
        while True:
            with guard:
                if progress['errors']:
                    raise RuntimeError(progress['errors'][0])
            batch = rpc(path, 'poll', session_id=identity, after=seq)
            native_text = batch.get('text', native_text)
            for step in batch['steps']:
                write('native', step)
                publisher.submit_step(step)
                seq = step['step_seq']
                native_text = step['text']
            publisher.publish_ready()
            pending = publisher.diagnostics()['unpublished_states']
            if pending and time.monotonic() - started - pending[0]['processed_until'] / 16000 > .8:
                raise RuntimeError('Pending paired state exceeded 800ms')
            if ingress_done.is_set() and soulx_done.is_set() and batch['ended']:
                break
            if time.monotonic() - started > len(audio) / 16000 + 10:
                raise TimeoutError('Dual ASR EOF completion exceeded ten seconds')
            stop.wait(.002)
        record['passed'] = True
    except Exception as exc:
        record.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    finally:
        stop.set()
        if reader.ident is not None:
            reader.join(12)
        if controller.ident is not None:
            controller.join(12)
        alive = reader.is_alive() or controller.is_alive()
        diagnostic = publisher.diagnostics()
        for frame in diagnostic['unpublished_states']:
            write('unpublished', dict(frame, unpublished_reason='eof_insufficient_coverage' if record['passed'] else 'case_failed'))
        write_json(output / f'{case_id}.pending.json', diagnostic)
        try:
            rpc(path, 'close', session_id=identity)
        except Exception as exc:
            record.update(passed=False, cleanup_error=str(exc), quarantined=True)
        if alive:
            record.update(passed=False, quarantined=True, cleanup_error='Dual ASR thread did not terminate')
        else:
            if frontend is not None:
                publisher.close('runtime_audio_case_end' if record['passed'] else 'case_failed')
                frontend.detach(aborted=True)
        for stream in streams.values():
            stream.close()
        current = context.get_user_turn(case_id, 'user-1') if frontend is not None else {}
        record.update(frames=frame_count, state_counts=dict(counts), raw_state_counts=dict(raw_counts),
                      playback_started_at=started,
                      online_text=current.get('text', ''),
                      drained_text=native_text,
                      drain_mode='real_complete_windows_only',
                      processed_samples=frontend.processed_until if frontend is not None else 0,
                      published_samples=last_frame['processed_until'] if last_frame else 0,
                      unpublished_states=len(diagnostic['unpublished_states']),
                      queue_peaks=diagnostic['queue_peaks'], ingress=progress, native_pcm=batch.get('pcm'),
                      elapsed_seconds=time.monotonic() - started)
    return record


def run(args):
    import numpy as np
    import soundfile as sf
    import soxr
    import torch
    if digest(args.manifest) != MANIFEST_SHA256:
        raise ValueError('Frozen FDB30 manifest digest differs')
    manifest = json.loads(args.manifest.read_text())
    samples = manifest['samples']
    if len(samples) != 30 or sum(s['duration_seconds'] for s in samples) > 1200:
        raise ValueError('Expected the original thirty-clip FDB manifest')
    if args.smoke:
        samples = [next(s for s in samples if s['task'] == task)
                   for task in ('smooth_turn_taking', 'pause_handling', 'user_interruption')]
    args.output.mkdir(exist_ok=False)
    write_json(args.output / 'input_manifest.json', dict(manifest, samples=samples))
    result = {'passed': False, 'cases': [], 'teacher_forcing': False, 'sensevoice_loaded': True,
              'control_mode': 'native_sensevoice', 'pairing_mode': 'audio_coverage', 'barrier': False,
              'timing_mode': 'realtime', 'manifest_sha256': digest(args.manifest),
              'source_commit': os.environ.get('SOULX_SOURCE_COMMIT')}
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.40, 0)
    try:
        controller, result['checkpoint_checks'] = load_controller(args)
        torch.set_num_threads(2)
        with torch.inference_mode():
            for _ in range(3):
                controller.process(np.zeros(2560, np.float32))
            controller.cascade_asr.recognize(np.zeros(53760, np.float32), 16000)
        torch.cuda.synchronize()
        for sample in samples:
            try:
                path = Path(sample['input'])
                for name, expected in sample['files'].items():
                    if digest(path.parent / name) != expected:
                        raise ValueError('Frozen audio or annotation digest differs')
                audio, rate = sf.read(path, dtype='float32')
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                if rate != 16000:
                    audio = soxr.resample(audio, rate, 16000)
                rms, peak = np.sqrt(np.mean(audio.astype(np.float64) ** 2)), float(np.max(np.abs(audio)))
                gain = min(.05 / rms, .9 / peak) if rms > 0 and peak > 0 else 1.
                record = run_case(controller, (audio * gain).astype(np.float32), sample['case_id'], args.socket, args.output)
                record['gain'] = float(gain)
            except Exception as exc:
                record = {'case_id': sample['case_id'], 'passed': False, 'error': str(exc), 'traceback': traceback.format_exc()}
            result['cases'].append(record)
            write_json(args.output / 'progress.json', result)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if record.get('quarantined'):
                raise RuntimeError('Model ownership quarantined after cleanup failure')
        result['passed'] = len(result['cases']) == len(samples) and all(v['passed'] for v in result['cases'])
    except Exception as exc:
        result.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        result['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        write_json(args.output / 'result.json', result)
    if not result['passed']:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    infer = commands.add_parser('run')
    for name in ('manifest', 'assets', 'check-source', 'socket', 'output'):
        infer.add_argument('--' + name, type=Path, required=True)
    infer.add_argument('--smoke', action='store_true')
    inspect = commands.add_parser('analyze')
    inspect.add_argument('--probe', type=Path, required=True)
    inspect.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    {'run': run, 'analyze': analyze}[args.command](args)


if __name__ == '__main__':
    main()
