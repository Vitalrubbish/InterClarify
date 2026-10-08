"""Launch the official DuplexCascade LLM server with local weights (P1.2).

The official repository only ships the real-time ``server.py`` entry point,
whose ``main()`` downloads the HF snapshot on every start.  For P1.2 we keep
the server **unmodified** but start it as a separate OS process from the
verified local snapshot (same arrangement as the P1.1 offline adapter):

- :class:`OfficialDuplexServer` builds and supervises the subprocess
  (``python -m interclarify.duplex.official_server ...``), streams its output
  to a log file and waits until the WebSocket port accepts connections;
- :func:`main` (the subprocess entry) imports the vendored official
  ``server.py`` from disk, builds the tokenizer exactly like the official
  ``main()``, loads the fixed weights with the official ``_load_model_state_dict``
  helper (``strict=False``) and runs the official ``KyutaiBridgeServer``
  unmodified.

Deliberate deviations from the official ``main()`` -- documented execution
supplements, not behavior changes:

1. the HF snapshot download is replaced by the local snapshot directory that
   P1.1 already verified byte-for-byte (``weight_sha256`` in the config);
2. the base model is loaded in bf16 so the 7B weights fit a 24 GB RTX 4090
   (same choice as the P1.1 adapter; weights themselves are unchanged);
3. model access happens fully offline;
4. ``train_cfg.json`` is not consulted for ``model_name`` /
   ``trust_remote_code`` (the pinned snapshot fixes both values: Qwen2-7B,
   no remote code); the tokenizer files still come from the snapshot first,
   exactly like the official code.

ASR and TTS stay external Kyutai services (ports 31607/31608); this process
only owns the control-model side of the official three-service architecture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Mirrors server.py SPECIAL_TOKENS (single source inside the project).
from .official_control import SPECIAL_TOKENS

DEFAULT_TTS_VOICE = "expresso/ex03-ex01_happy_001_channel1_334s.wav"


def verify_weight_sha256(snapshot_dir: Path | str, filename: str, expected_sha256: str) -> str:
    """Stream-hash a weight file and raise if it differs from the pinned digest."""
    path = Path(snapshot_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f"weight file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"weight digest mismatch for {path}: expected {expected_sha256}, got {actual}"
        )
    return actual


class OfficialDuplexServer:
    """Subprocess manager for the unmodified official LLM server.

    Parameters mirror the official ``server.py`` CLI.  ``start()`` returns
    once the port accepts TCP connections (the model must be loaded by then,
    because ``KyutaiBridgeServer.run`` binds only after ``main()`` finishes
    loading); ``stop()`` terminates the process group.
    """

    def __init__(
        self,
        *,
        snapshot_dir: Path | str,
        base_model_path: Path | str,
        source_root: Path | str,
        llm_port: int = 31606,
        stt_ws: str = "ws://127.0.0.1:31607/api/asr-streaming",
        tts_ws: str = "ws://127.0.0.1:31608/api/tts_streaming",
        device: str = "cuda",
        dtype: str = "bfloat16",
        max_new_tokens: int = 64,
        overlap_window_s: float = 0.6,
        api_key: str = "public_token",
        tts_voice: str = DEFAULT_TTS_VOICE,
        stt_pre_silence_s: float = 0.0,
        python_exe: Optional[str] = None,
        log_path: Optional[Path | str] = None,
        ready_timeout_s: float = 900.0,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        self.base_model_path = Path(base_model_path)
        self.source_root = Path(source_root)
        self.llm_port = int(llm_port)
        self.stt_ws = stt_ws
        self.tts_ws = tts_ws
        self.device = device
        self.dtype = dtype
        self.max_new_tokens = int(max_new_tokens)
        self.overlap_window_s = float(overlap_window_s)
        self.api_key = api_key
        self.tts_voice = tts_voice
        self.stt_pre_silence_s = float(stt_pre_silence_s)
        self.python_exe = python_exe or sys.executable
        self.log_path = Path(log_path) if log_path else None
        self.ready_timeout_s = float(ready_timeout_s)
        self.env = dict(env) if env else None
        self.process: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.llm_port}/"

    def build_command(self) -> List[str]:
        """Assemble the subprocess argv (also used by tests)."""
        return [
            self.python_exe,
            "-m",
            "interclarify.duplex.official_server",
            "--snapshot",
            str(self.snapshot_dir),
            "--base-model-path",
            str(self.base_model_path),
            "--source-root",
            str(self.source_root),
            "--port",
            str(self.llm_port),
            "--device",
            self.device,
            "--dtype",
            self.dtype,
            "--max-new-tokens",
            str(self.max_new_tokens),
            "--overlap-window-s",
            str(self.overlap_window_s),
            "--stt-ws",
            self.stt_ws,
            "--tts-ws",
            self.tts_ws,
            "--api-key",
            self.api_key,
            "--tts-voice",
            self.tts_voice,
            "--stt-pre-silence-s",
            str(self.stt_pre_silence_s),
        ]

    def start(self) -> None:
        """Launch the server process and block until the port is ready."""
        if self.process is not None:
            raise RuntimeError("server already started")
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        src_dir = str(Path(__file__).resolve().parents[2])
        python_path = env.get("PYTHONPATH", "")
        if src_dir not in python_path.split(os.pathsep):
            env["PYTHONPATH"] = src_dir + (os.pathsep + python_path if python_path else "")
        env.setdefault("HF_HUB_OFFLINE", "1")
        env.setdefault("TRANSFORMERS_OFFLINE", "1")
        log_handle = None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = self.log_path.open("ab")
        try:
            self.process = subprocess.Popen(
                self.build_command(),
                stdout=log_handle if log_handle is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        finally:
            if log_handle is not None:
                log_handle.close()
        deadline = time.monotonic() + self.ready_timeout_s
        while True:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"official server exited during startup (rc={self.process.returncode}); "
                    f"see log: {self.log_path}"
                )
            if self._port_open():
                return
            if time.monotonic() >= deadline:
                self.stop()
                raise TimeoutError(f"official server not ready within {self.ready_timeout_s}s")
            time.sleep(1.0)

    def stop(self) -> None:
        """Terminate the server process (idempotent)."""
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=15)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    @staticmethod
    def _probe_port(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            return False

    def _port_open(self) -> bool:
        return self._probe_port(self.llm_port)

    def __enter__(self) -> "OfficialDuplexServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def _load_official_server_module(source_root: Path) -> Any:
    """Import the vendored official ``server.py`` without modifying it."""
    server_file = source_root / "server.py"
    if not server_file.is_file():
        raise FileNotFoundError(f"official DuplexCascade server.py not found: {server_file}")
    spec = importlib.util.spec_from_file_location(
        "interclarify_official_duplexcascade_server", server_file
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import official server from {server_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: Optional[List[str]] = None) -> int:
    """Subprocess entry: build and run the official server from local assets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="verified DuplexCascade snapshot dir")
    parser.add_argument("--base-model-path", required=True, help="base model snapshot dir")
    parser.add_argument("--source-root", required=True, help="official DuplexCascade checkout")
    parser.add_argument("--port", type=int, default=31606)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--overlap-window-s", type=float, default=0.6)
    parser.add_argument("--stt-ws", default="ws://127.0.0.1:31607/api/asr-streaming")
    parser.add_argument("--tts-ws", default="ws://127.0.0.1:31608/api/tts_streaming")
    parser.add_argument("--api-key", default="public_token")
    parser.add_argument("--tts-voice", default=DEFAULT_TTS_VOICE)
    parser.add_argument("--stt-pre-silence-s", type=float, default=0.0)
    args = parser.parse_args(argv)

    import torch
    from transformers import AutoTokenizer

    snapshot_dir = Path(args.snapshot)
    base_model_path = Path(args.base_model_path)
    source_root = Path(args.source_root)

    official = _load_official_server_module(source_root)

    tokenizer_dir = snapshot_dir / "tokenizer"
    tokenizer_source = (
        str(tokenizer_dir)
        if tokenizer_dir.is_dir() and any(tokenizer_dir.iterdir())
        else str(base_model_path)
    )
    try:
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, use_fast=True, trust_remote_code=False)
    except Exception:
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, use_fast=False, trust_remote_code=False)
    tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})

    llm_model = official.Model(
        tokenizer=tokenizer,
        model_name=str(base_model_path),
        trust_remote_code=False,
        torch_dtype=getattr(torch, args.dtype),
        attn_implementation="sdpa",
    )
    llm_model.enable_lora_adapter()
    llm_model.to(args.device)
    llm_model.eval()

    state_dict = official._load_model_state_dict(snapshot_dir)
    llm_model.load_state_dict(state_dict, strict=False)
    del state_dict

    server = official.KyutaiBridgeServer(
        llm_model=llm_model,
        tokenizer=tokenizer,
        llm_device=args.device,
        kyutai_stt_ws=args.stt_ws,
        kyutai_tts_ws=args.tts_ws,
        kyutai_api_key=args.api_key,
        kyutai_tts_voice=args.tts_voice,
        overlap_window_s=args.overlap_window_s,
        max_new_tokens=args.max_new_tokens,
        stt_pre_silence_s=args.stt_pre_silence_s,
    )
    asyncio.run(server.run(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
