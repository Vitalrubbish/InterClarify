"""Exercise synced X-Talk micro-turn execution against real official weights."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path


def source_digest(directory: Path) -> str:
    """Hash sorted Python source paths and contents for worktree provenance."""
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*.py')):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class NativePCM:
    """Use synthetic PCM to validate native output ownership with a real LLM."""

    async def async_synthesize_stream(self, text):
        """Return a short headless audio buffer for each native TTS segment."""
        yield b'\x00\x00' * 9600


async def run_smoke(args) -> dict:
    """Run user and silent windows through the actual official model service."""
    import xtalk
    from xtalk.duplex_control.micro_turn import MicroTurnAssembler
    from xtalk.duplex_control.runtime_adapter import DuplexRuntimeAdapter
    from xtalk.duplex_control.timeline import DuplexTimelineRecorder
    from xtalk.models import Models, TTS
    from xtalk.serving.event_bus import EventBus, EventDispatchMode
    from xtalk.serving.events import (
        ASRResultPartial, DuplexProtocolError, DuplexProtocolParsed,
        LLMAgentResponseUpdate, TTSChunkPlayed, TTSChunkReady,
        TTSPlaybackFinished, TurnTTSFlushRequested,
    )
    from xtalk.serving.modules.tts_manager import TTSManager
    from xtalk.serving.modules.tts_response_coordinator import TTSResponseCoordinator
    from xtalk.serving.modules.tts_playback_manager import TTSPlaybackManager

    args.output.mkdir(parents=True, exist_ok=True)
    bus = EventBus(enable_history=True, max_history=10000)
    assembler = MicroTurnAssembler(bus, 'official-smoke', {'duplex_auto_tick': False})
    adapter = DuplexRuntimeAdapter(bus, 'official-smoke', {'duplex_model_url': args.model_url,
        'duplex_timeout_seconds': 120})
    recorder = DuplexTimelineRecorder(bus, 'official-smoke', {'duplex_timeline_dir': str(args.output)})
    tts = TTSManager(bus, 'official-smoke', Models({TTS: NativePCM()}))
    coordinator = TTSResponseCoordinator(bus, 'official-smoke')
    playback = TTSPlaybackManager(bus, 'official-smoke')

    async def acknowledge(event):
        """Confirm headless delivery without claiming physical audio quality."""
        await bus.publish(TTSChunkPlayed(session_id='official-smoke', response_id=event.response_id),
                          mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)

    bus.subscribe(TTSChunkReady, acknowledge, priority=-20)
    start = time.monotonic()
    windows = []
    try:
        for text in ('What is', 'What is the capital of France?'):
            await bus.publish(ASRResultPartial(session_id='official-smoke', text=text),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
            await asyncio.sleep(0.6)
            before = time.monotonic()
            await assembler.flush()
            windows.append({'elapsed': time.monotonic() - start, 'inference_seconds': time.monotonic() - before})
        for _ in range(args.silent_windows):
            await asyncio.sleep(0.6)
            before = time.monotonic()
            await assembler.flush()
            windows.append({'elapsed': time.monotonic() - start, 'inference_seconds': time.monotonic() - before})
        errors = [vars(event) for event in bus.get_history(event_type=DuplexProtocolError.TYPE)]
        outputs = [vars(event) for event in bus.get_history(event_type=DuplexProtocolParsed.TYPE)]
        answers = [event.text for event in bus.get_history(event_type=LLMAgentResponseUpdate.TYPE)]
        for event in bus.get_history(event_type=TurnTTSFlushRequested.TYPE):
            await bus.publish(TTSPlaybackFinished(session_id='official-smoke', response_id=event.response_id),
                              mode=EventDispatchMode.WAIT_UNTIL_COMPLETE)
        return {'status': 'PASS' if outputs and answers and not errors else 'FAIL',
            'model_url': args.model_url, 'xtalk_source': str(Path(xtalk.__file__).resolve()),
            'source_sha256': source_digest(Path(xtalk.__file__).parent),
            'windows': windows, 'outputs': outputs, 'errors': errors,
            'answers': answers, 'heard': adapter.heard,
            'note': 'Real official LLM; scripted ASR prefixes and synthetic PCM. Real audio/FDB acceptance pending.'}
    finally:
        await assembler.shutdown()
        await adapter.shutdown()
        await tts.shutdown()
        await playback.shutdown()
        await coordinator.shutdown()
        await bus.shutdown()
        await recorder.shutdown()


def main() -> None:
    """Write the remote official-model smoke report and signal failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-url', default='http://127.0.0.1:8006')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--silent-windows', type=int, default=10)
    args = parser.parse_args()
    report = asyncio.run(run_smoke(args))
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'status': report['status'], 'outputs': len(report['outputs']),
                      'errors': len(report['errors']), 'output': str(args.output)}))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
