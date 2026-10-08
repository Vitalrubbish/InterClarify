"""Headless real-time duplex harness (P1.2).

This package connects the *unmodified* official DuplexCascade runtime (separate
Kyutai STT/TTS services plus the official ``server.py`` control model) to a
scripted audio source.  It proves the P1.2 acceptance points without a browser:

- :mod:`interclarify.realtime.clock` -- real / virtual pacing clocks;
- :mod:`interclarify.realtime.playback` -- the single playback owner
  (virtual sink for headless runs, sounddevice sink for local machines);
- :mod:`interclarify.realtime.scenarios` -- scripted user-audio scenarios
  with declarative expectations;
- :mod:`interclarify.realtime.client` -- the headless full-duplex WebSocket
  client that streams microphone audio, receives ASR/control/TTS events and
  feeds the playback owner.

The client speaks exactly the browser protocol of the official
``server.py`` (binary float32 PCM frames + JSON control messages); no server
code is modified.
"""

from .clock import Clock, RealClock, VirtualClock, make_clock
from .playback import PlaybackSink, SoundDevicePlaybackSink, VirtualPlaybackSink
from .scenarios import Segment, Scenario, load_audio_mono, load_scenarios
from .client import DuplexSessionClient, SessionResult

__all__ = [
    "Clock",
    "RealClock",
    "VirtualClock",
    "make_clock",
    "PlaybackSink",
    "SoundDevicePlaybackSink",
    "VirtualPlaybackSink",
    "Segment",
    "Scenario",
    "load_audio_mono",
    "load_scenarios",
    "DuplexSessionClient",
    "SessionResult",
]
