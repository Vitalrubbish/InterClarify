"""Run frozen FDB30 through native dual frontend and cancellable half-duplex replies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import threading
import time
import traceback

import numpy as np

from duplex_replies import ReplySession
from native_frontend_probe import (MANIFEST_SHA256, cleanup, digest, full_warmup,
                                   load_audio, load_native_controller, quantize, replay,
                                   warmup_audio, write_json, X2Process)


class Trace:
    """Persist thread-safe events using the input playback clock."""

    def __init__(self, output):
        self.stream = (output / 'events.jsonl').open('x')
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.counts = {}

    def __call__(self, event, **fields):
        with self.lock:
            self.counts[event] = self.counts.get(event, 0) + 1
            self.stream.write(json.dumps(dict(event=event, time=time.monotonic()-self.started, **fields),
                                         ensure_ascii=False) + '\n')
            self.stream.flush()


class JointReplyConsumer:
    """Consume each committed state once without repeating cumulative X2 text."""

    def __init__(self, session, trace):
        self.session, self.trace = session, trace
        self.consumed = ''
        self.previous_step = -1

    def consume(self, row):
        if row['step_id'] != self.previous_step + 1:
            raise ValueError('Missing or repeated published state')
        self.previous_step = row['step_id']
        state = row['receipts']['controller']['state']
        text = row['snapshot']['text']
        if not text.startswith(self.consumed):
            raise ValueError('Published X2 prefix changed')
        token = state['state_token']
        self.trace('joint_state_consumed', step_id=row['step_id'], token=token,
                   accepted=state['state_accepted'], raw_token=state['raw_token'],
                   observed_until=state['state_observed_until']/16000,
                   processed_until=state['state_processed_until']/16000,
                   published_at=row['batch_published_at'], text=text)
        self.session.check()
        if not state['state_accepted']:
            return
        if token == '<|user_nonidle|>':
            self.session.cancel('soulx_nonidle')
        elif token == '<|user_complete|>':
            delta = text[len(self.consumed):].strip()
            if not delta:
                self.trace('complete_without_new_text', step_id=row['step_id'])
                return
            if self.session.busy():
                self.session.cancel('soulx_new_complete')
            if self.session.start(delta):
                self.consumed = text


def run_case(model, worker, sample, args):
    folder = args.output / 'samples' / sample['subset'] / sample['id']
    folder.mkdir(parents=True, exist_ok=False)
    values, gain = load_audio(sample)
    original_seconds = len(values)/16000
    audio = np.concatenate((quantize(values), np.zeros(8*16000, np.float32)))
    trace = Trace(folder)
    session = consumer = None
    error = None

    def recognize_tail(audio, **kwargs):
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        import torch
        with torch.inference_mode():
            raw = model.cascade_asr.sensevoice_model.generate(
                input=audio, cache={}, language='en', use_itn=True, batch_size=16)
        return model.cascade_asr.clean_sensevoice_text(rich_transcription_postprocess(raw[0]['text']))

    def on_batch(row, started):
        nonlocal session, consumer
        if session is None:
            trace.started = started
            session = ReplySession(started, trace, recognize_tail,
                str(args.socket_root/'qwen.sock'), str(args.socket_root/'indextts.sock'),
                sample['case_id'], output=folder)
            consumer = JointReplyConsumer(session, trace)
        consumer.consume(row)

    def on_finish(record):
        if session is not None:
            deadline = time.monotonic() + 60
            while record['passed'] and session.busy():
                session.check()
                if time.monotonic() > deadline:
                    raise TimeoutError('Final reply did not finish within 60 seconds')
                time.sleep(.02)
            session.close(minimum_seconds=original_seconds)

    try:
        record = replay(model, worker, audio, sample['case_id'], folder, True,
                        compress=True, on_batch=on_batch, on_finish=on_finish)
    except Exception:
        error = traceback.format_exc()
        if session is not None:
            session.close(minimum_seconds=original_seconds)
        record = {'passed': False, 'error': error}
    finally:
        trace.stream.close()
    record.update(case_id=sample['case_id'], subset=sample['subset'], id=sample['id'],
                  original_seconds=original_seconds, gain=gain, input_sha256=digest(Path(sample['input'])),
                  event_counts=trace.counts)
    if (folder/'output.wav').exists():
        record['recording'] = {'kind': 'live_monotonic_playback_capture', 'posthoc_audio_synthesis': False,
            **{key: digest(folder/name) for name, key in [('output.wav','audio_sha256'),
                ('playback_frames.jsonl','frames_sha256'),('events.jsonl','events_sha256')]}}
    write_json(folder/'result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','assets','upstream','asr-python','warmup-audio','output','socket-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    import torch
    if digest(args.manifest) != MANIFEST_SHA256:
        raise ValueError('Frozen FDB30 manifest differs')
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(args.manifest.read_text())
    if len(manifest['samples']) != 30:
        raise ValueError('Expected all 30 frozen cases')
    samples = manifest['samples']
    if args.smoke:
        ids = {'candor_turn_taking-17', 'candor_pause_handling-16', 'synthetic_user_interruption-104'}
        samples = [s for s in samples if s['case_id'] in ids]
    report = {'passed':False, 'manifest_sha256':MANIFEST_SHA256, 'samples':samples,
              'scope':'smoke' if args.smoke else 'fixed_fdb30', 'cases':[]}
    write_json(args.output/'input_manifest.json', manifest)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.90)
    worker = None
    try:
        worker = X2Process(args.asr_python, args.assets, args.output)
        native = load_native_controller(args.upstream, args.assets/'models/soulx-duplug',
            args.assets/'models/sensevoice-small', args.output/'assets')
        model = native.model
        native.detach()
        # Serialize the shared SenseVoice teacher and audible-tail history recognition.
        sensevoice = model.cascade_asr.sensevoice_model
        original_generate = sensevoice.generate
        asr_lock = threading.RLock()
        def locked_generate(*args, **kwargs):
            with asr_lock:
                return original_generate(*args, **kwargs)
        sensevoice.generate = locked_generate
        audio, report['warmup_normalization'] = warmup_audio(args.warmup_audio)
        report['warmup'] = full_warmup(model, worker, audio, args.output)
        write_json(args.output/'warmup.json', report['warmup'])
        if not report['warmup']['passed']:
            raise RuntimeError('Frontend warmup coverage failed')
        for sample in samples:
            record = run_case(model, worker, sample, args)
            report['cases'].append(record)
            write_json(args.output/'progress.json',report)
            if not record['passed']:
                raise RuntimeError('Preserve failed sample and stop run: '+sample['case_id'])
        report['passed'] = len(report['cases']) == len(samples)
    except Exception:
        report['error'] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if worker:
            worker.close()
        write_json(args.output/'result.json',report)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
