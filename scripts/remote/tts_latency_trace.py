"""Write correlated CPU wall-clock events without mixing process clocks."""
from __future__ import annotations

import contextvars
import json
import os
import threading
import time
from contextlib import contextmanager

_context = contextvars.ContextVar('tts_trace', default={})
_lock = threading.Lock()


@contextmanager
def trace_scope(request_id: str, response_id: str):
    """Bind the response being processed by this worker."""
    token = _context.set({'request_id': request_id, 'response_id': response_id})
    try:
        yield
    finally:
        _context.reset(token)


def emit(event: str, **fields) -> None:
    """Append an event only when a trace output was explicitly requested."""
    path = os.environ.get('XTALK_TTS_TRACE')
    if not path:
        return
    row = {**_context.get(), **fields, 'event': event,
           'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid(),
           'clock_domain': f'process:{os.getpid()}'}
    with _lock:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


@contextmanager
def span(event: str, **fields):
    """Record CPU entry, exit and error without synchronizing the GPU."""
    emit(event + '.start', **fields)
    try:
        yield
    except Exception as error:
        emit(event + '.error', error=type(error).__name__, **fields)
        raise
    finally:
        emit(event + '.end', **fields)
