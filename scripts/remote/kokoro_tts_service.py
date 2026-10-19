"""Synthesize committed short segments using frozen local Kokoro assets."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
from pathlib import Path
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

LOG = logging.getLogger(__name__)


def spoken_time_text(text):
    """Expand valid clock times only in explicit time contexts for speech."""
    small = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
             'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
             'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']

    def number(value):
        return small[value] if value < 20 else ['twenty', 'thirty', 'forty', 'fifty'][value // 10 - 2] + (
            ' ' + small[value % 10] if value % 10 else '')

    def replace(match):
        hour, minute = int(match['hour']), int(match['minute'])
        ending = "o'clock" if minute == 0 else ('oh ' + number(minute) if minute < 10 else number(minute))
        return match['context'] + number(hour) + ' ' + ending

    return re.sub(r'(?P<context>\b(?:at|around|by|from|until|before|after)\s+)'
                  r'(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?![\d:])',
                  replace, text, flags=re.IGNORECASE)


class KokoroEngine:
    """Own fixed weights and one voice; serialize GPU segment computation."""

    def __init__(self, snapshot: Path, device='cuda'):
        started = time.monotonic()
        import torch
        from kokoro import KModel, KPipeline
        self.model = KModel(config=str(snapshot / 'config.json'),
                            model=str(snapshot / 'kokoro-v1_0.pth')).to(device).eval()
        self.pipeline = KPipeline(lang_code='a', model=self.model)
        self.voice = str(snapshot / 'voices/af_heart.pt')
        self.pipeline.load_voice(self.voice)
        self.lock = threading.Lock()
        self.info = {'backend': 'kokoro', 'snapshot': str(snapshot.resolve()),
                     'voice': 'af_heart', 'sample_rate': 48000, 'format': 'pcm_s16le',
                     'channels': 1, 'torch': torch.__version__,
                     'load_seconds': time.monotonic()-started}

    def synthesize(self, text):
        """Return resampled mono PCM16; native segment synthesis runs to completion."""
        from scipy.signal import resample_poly
        with self.lock:
            chunks = [result.audio.detach().cpu().numpy().reshape(-1)
                      for result in self.pipeline(spoken_time_text(text), voice=self.voice, speed=1, split_pattern=None)]
        if not chunks or not any(len(chunk) for chunk in chunks):
            raise RuntimeError('Kokoro produced no audio')
        audio = resample_poly(np.concatenate(chunks), 2, 1)
        if not np.isfinite(audio).all():
            raise RuntimeError('Kokoro produced non-finite audio')
        return (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()


class SegmentRequest(BaseModel):
    """Bind each bounded segment to an opaque client response generation."""

    generation: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=160)
    voice: str = 'af_heart'


def create_app(engine):
    """Serve synthesis only; playback and cancellation ownership stay in X-Talk."""
    app = FastAPI()

    @app.get('/health')
    def health():
        import resource
        return {'status': 'ok', **engine.info, 'warmed_up': True,
                'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}

    @app.post('/v1/synthesize')
    def synthesize(request: SegmentRequest):
        if request.voice != 'af_heart' or not request.text.strip():
            raise HTTPException(400, 'Expected af_heart and nonempty segment')
        started = time.monotonic()
        pcm = engine.synthesize(request.text)
        completed = time.monotonic()
        LOG.info(json.dumps({'event': 'kokoro_segment', 'generation': request.generation,
            'sequence': request.sequence, 'text': request.text, 'started_monotonic': started,
            'completed_monotonic': completed, 'audio_seconds': len(pcm) / 96000}))
        return {'generation': request.generation, 'sequence': request.sequence,
                'sample_rate': 48000, 'channels': 1, 'format': 'pcm_s16le',
                'pcm': base64.b64encode(pcm).decode(), 'compute_seconds': completed - started}
    return app


def main():
    """Load and warm short and longer text segments before exposing readiness."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8004)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = KokoroEngine(args.snapshot)
    for text in ('Yes, that works.', 'Did you mean Tuesday at nine thirty, or Thursday afternoon?'):
        if not engine.synthesize(text):
            raise RuntimeError('Kokoro warmup failed')
    import uvicorn
    uvicorn.run(create_app(engine), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
