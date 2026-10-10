"""Prepare and inspect round-one X-Talk model services independently."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs/xtalk_round1.yaml"


def read_config(path: Path) -> dict:
    """Read the round-one model preparation configuration."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config["schema_version"] != 1:
        raise ValueError("Unsupported round-one schema version")
    return config


def write_json(path: Path, data: dict) -> None:
    """Write preparation evidence as UTF-8 JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def select_gpu(index: int) -> None:
    """Select a logical GPU while preserving the job's device allocation."""
    if index < 0:
        raise ValueError("GPU index must be nonnegative")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None:
        devices = [device.strip() for device in visible.split(",") if device.strip()]
        if index >= len(devices):
            raise ValueError(f"GPU index {index} exceeds CUDA_VISIBLE_DEVICES={visible!r}")
        os.environ["CUDA_VISIBLE_DEVICES"] = devices[index]
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(index)


def model_path(config: dict, root: Path, role: str) -> Path:
    """Return a downloaded snapshot that matches the configured model ID."""
    lock = json.loads((root / "models.lock.json").read_text(encoding="utf-8"))
    entry = lock["models"][role]
    requested = config["models"][role]
    if entry["model_id"] != requested["model_id"]:
        raise ValueError(f"Locked model ID differs for {role}")
    if requested["revision"] is not None and entry["revision"] != requested["revision"]:
        raise ValueError(f"Locked revision differs for {role}")
    if not entry["snapshot_path"]:
        raise ValueError(f"Model download is incomplete for {role}")
    path = Path(entry["snapshot_path"])
    if not path.is_dir():
        raise ValueError(f"Missing downloaded snapshot for {role}: {path}")
    return path


def check_dependencies(config: dict, role: str) -> dict:
    """Verify the active conda environment matches the pinned versions.

    The image must ship the exact dependencies the config expects (notably the
    flash-attn wheel required by MOSS ``flash_attention_2``); checking at
    startup turns silent version drift into a clear failure instead of a
    confusing downstream crash.
    """
    from importlib import metadata

    candidates = config.get("dependency_candidates", {})
    dist_names = {
        "torch": ("torch",),
        "transformers": ("transformers",),
        "vllm": ("vllm",),
        "flash_attn": ("flash_attn", "flash-attn"),
        "onnxruntime": ("onnxruntime",),
        "kaldi_native_fbank": ("kaldi-native-fbank", "kaldi_native_fbank"),
    }

    def probe(import_name: str) -> dict:
        installed = None
        for name in dist_names.get(import_name, (import_name,)):
            try:
                installed = metadata.version(name)
                break
            except metadata.PackageNotFoundError:
                continue
        importable, error = True, None
        try:
            __import__(import_name)
        except Exception as exc:  # noqa: BLE001 - record the import failure verbatim
            importable, error = False, f"{type(exc).__name__}: {exc}"
        return {"installed": installed, "importable": importable, "import_error": error}

    expected: dict[str, str | None] = {}
    if role == "asr":
        expected["transformers"] = candidates.get("asr_transformers")
    elif role == "llm":
        expected["vllm"] = candidates.get("vllm")
    elif role == "turn_detector":
        expected["onnxruntime"] = candidates.get("turnsense_onnxruntime")
        expected["kaldi_native_fbank"] = candidates.get(
            "turnsense_kaldi_native_fbank"
        )
    elif role == "tts":
        expected["torch"] = candidates.get("moss_torch")
        expected["transformers"] = candidates.get("moss_transformers")
        if config["services"]["tts"].get("attn_impl") == "flash_attention_2":
            expected["flash_attn"] = candidates.get("moss_flash_attn")
    else:
        raise ValueError(f"Unknown dependency role: {role}")

    packages: dict[str, dict] = {}
    for package, want in expected.items():
        info = probe(package)
        info["expected"] = want
        installed = info["installed"]
        if want is None:
            version_ok = installed is not None
        elif installed is None:
            version_ok = False
        elif "+" in want:
            version_ok = installed == want
        else:
            version_ok = installed.split("+")[0] == want
        info["version_ok"] = version_ok
        info["ok"] = version_ok and info["importable"]
        packages[package] = info

    return {"role": role, "ok": all(info["ok"] for info in packages.values()), "packages": packages}


def download_models(config: dict, root: Path) -> None:
    """Resolve immutable revisions once and download resumable snapshots."""
    from huggingface_hub import HfApi, snapshot_download

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "models.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {"models": {}}
    api = HfApi()
    for role, requested in config["models"].items():
        entry = lock["models"].get(role)
        if entry is None:
            revision = api.model_info(requested["model_id"], revision=requested["revision"]).sha
            if revision is None:
                raise ValueError(f"No immutable revision returned for {role}")
            entry = {"model_id": requested["model_id"], "revision": revision, "snapshot_path": None}
            lock["models"][role] = entry
            write_json(lock_path, lock)
        elif entry["model_id"] != requested["model_id"] or (
            requested["revision"] is not None and requested["revision"] != entry["revision"]
        ):
            raise ValueError(f"Existing model lock differs for {role}; use a new model root")
        path = snapshot_download(
            repo_id=entry["model_id"], revision=entry["revision"], cache_dir=str(root / "cache")
        )
        entry["snapshot_path"] = str(Path(path).resolve())
        write_json(lock_path, lock)
        print(f"[download] {role}: {entry['model_id']}@{entry['revision']}", flush=True)


def new_report_directory(output: Path, config_path: Path, model_root: Path) -> None:
    """Create fresh evidence with the configuration and immutable model lock."""
    lock_bytes = (model_root / "models.lock.json").read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    (output / "config.yaml").write_bytes(config_path.read_bytes())
    (output / "models.lock.json").write_bytes(lock_bytes)


def asr_smoke(config: dict, args: argparse.Namespace) -> None:
    """Replay mono 16 kHz audio through the official stateful streaming API."""
    import numpy as np
    import soundfile as sf
    from qwen_asr import Qwen3ASRModel

    audio, rate = sf.read(args.audio, dtype="float32", always_2d=False)
    stream = dict(config["asr_streaming"])
    if rate != stream["sample_rate"] or audio.ndim != 1 or not audio.size:
        raise ValueError("ASR input must be a nonempty mono 16 kHz WAV")
    if args.chunk_seconds is not None:
        if args.chunk_seconds <= 0:
            raise ValueError("chunk-seconds must be positive")
        stream["chunk_size_sec"] = args.chunk_seconds
    new_report_directory(args.output, args.config, args.model_root)
    service = config["services"]["asr"]
    started = time.monotonic()
    model = Qwen3ASRModel.LLM(
        model=str(model_path(config, args.model_root, "asr")),
        gpu_memory_utilization=service["gpu_memory_utilization"],
        max_new_tokens=service["max_new_tokens"],
    )
    load_seconds = time.monotonic() - started
    state = model.init_streaming_state(
        chunk_size_sec=stream["chunk_size_sec"],
        unfixed_chunk_num=stream["unfixed_chunk_num"],
        unfixed_token_num=stream["unfixed_token_num"],
    )
    # Warm up the streaming/decode path: the first call carries a one-off cost
    # (kernel/graph init) that otherwise dominates the reported first partial.
    warm = np.zeros(int(rate * stream["chunk_size_sec"]), dtype=np.float32)
    warm_state = model.init_streaming_state(
        chunk_size_sec=stream["chunk_size_sec"],
        unfixed_chunk_num=stream["unfixed_chunk_num"],
        unfixed_token_num=stream["unfixed_token_num"],
    )
    model.streaming_transcribe(warm, warm_state)
    model.streaming_transcribe(warm, warm_state)
    step = int(rate * stream["input_step_ms"] / 1000)
    started = time.monotonic()
    previous = ""
    first_partial = None
    first_partial_audio = None
    decode_seconds = 0.0
    revisions = 0
    with (args.output / "asr_events.jsonl").open("w", encoding="utf-8") as events:
        for offset in range(0, len(audio), step):
            chunk = np.asarray(audio[offset : offset + step], dtype=np.float32)
            end_seconds = (offset + len(chunk)) / rate
            time.sleep(max(0.0, end_seconds - (time.monotonic() - started)))
            call_start = time.monotonic()
            model.streaming_transcribe(chunk, state)
            decode_seconds += time.monotonic() - call_start
            text = state.text or ""
            arrival = time.monotonic() - started
            rewritten = text != previous and not text.startswith(previous)
            revisions += int(rewritten)
            if text and first_partial is None:
                first_partial = arrival
                first_partial_audio = end_seconds
            event = {
                "audio_seconds": end_seconds, "arrival_seconds": arrival,
                "text": text, "rewritten": rewritten,
            }
            events.write(json.dumps(event, ensure_ascii=False) + "\n")
            events.flush()
            previous = text
        call_start = time.monotonic()
        model.finish_streaming_transcribe(state)
        decode_seconds += time.monotonic() - call_start
        events.write(json.dumps({"final": True, "arrival_seconds": time.monotonic() - started,
                                 "text": state.text}, ensure_ascii=False) + "\n")
    duration = len(audio) / rate
    write_json(args.output / "asr_report.json", {
        "status": "COMPLETE" if state.text else "EMPTY_TRANSCRIPT",
        "streaming": stream, "audio_seconds": duration,
        "audio_sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        "model_load_seconds": load_seconds, "first_partial_seconds": first_partial,
        "first_partial_audio_seconds": first_partial_audio,
        "revisions": revisions, "decode_seconds": decode_seconds,
        "decode_rtf": decode_seconds / duration,
        "replay_wall_seconds": time.monotonic() - started, "final_text": state.text,
        "note": "Model smoke only; correctness and X-Talk integration require separate acceptance.",
    })
    if not state.text:
        raise RuntimeError("ASR produced no final transcript; inspect the report")


async def tts_smoke(config: dict, args: argparse.Namespace) -> None:
    """Send incremental text while receiving and saving streamed PCM audio."""
    from xtalk.models.tts.moss_tts_realtime import MossTTSRealtime

    if not args.reference.is_file() or args.gap_seconds <= 0:
        raise ValueError("Reference audio must exist and gap-seconds must be positive")
    new_report_directory(args.output, args.config, args.model_root)
    service = config["services"]["tts"]
    client = MossTTSRealtime(
        base_url=args.url or f"http://{service['host']}:{service['port']}",
        voices=[{"name": "round1", "path": str(args.reference.resolve())}],
    )
    started = time.monotonic()
    await client.start()
    first_audio = None
    flush_seconds = None
    chunks = []

    async def receive_audio() -> None:
        """Consume PCM concurrently with text delivery."""
        nonlocal first_audio
        async for chunk in client.audio_stream():
            if chunk and first_audio is None:
                first_audio = time.monotonic() - started
            chunks.append(chunk)

    collector = asyncio.create_task(receive_audio())
    # Optionally split each provided text into fixed-size word chunks so the
    # service sees the text arrive incrementally (LLM-style streaming) rather
    # than as one big prefill.
    texts: list[str] = []
    for text in args.text:
        if args.stream_chunk_words and args.stream_chunk_words > 0:
            words = text.split()
            for index in range(0, len(words), args.stream_chunk_words):
                texts.append(" ".join(words[index:index + args.stream_chunk_words]) + " ")
        else:
            texts.append(text)
    try:
        for index, text in enumerate(texts):
            await client.append_text(text)
            if index + 1 < len(texts):
                await asyncio.sleep(args.gap_seconds)
        flush_seconds = time.monotonic() - started
        await client.flush()
        await asyncio.wait_for(collector, timeout=args.timeout_seconds)
    finally:
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        await asyncio.wait_for(client.stop(), timeout=10)
    pcm = b"".join(chunks)
    rate = client.output_sample_rate
    with wave.open(str(args.output / "tts.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    write_json(args.output / "tts_report.json", {
        "status": "COMPLETE" if pcm else "EMPTY_AUDIO",
        "text_chunks": texts, "text_chunk_count": len(texts),
        "stream_chunk_words": args.stream_chunk_words,
        "sample_rate": rate,
        "first_audio_seconds": first_audio, "flush_seconds": flush_seconds,
        "audio_before_flush": first_audio is not None and first_audio < flush_seconds,
        "wall_seconds": time.monotonic() - started, "audio_seconds": len(pcm) / (2 * rate),
        "audio_chunks": len(chunks),
        "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        "note": "Report cold and warm runs separately; COMPLETE is not a quality verdict.",
    })
    if not pcm:
        raise RuntimeError("TTS produced no audio; inspect the report")


def serve(config: dict, args: argparse.Namespace) -> None:
    """Start one model service inside its configured conda environment."""
    role = args.service
    service = config["services"][role]
    select_gpu(service["gpu_index"] if args.gpu_index is None else args.gpu_index)
    command = ["conda", "run", "--no-capture-output", "-n", config["environments"][role]]
    if role == "asr":
        script = Path(__file__).with_name("qwen3_asr_service.py")
        stream = config["asr_streaming"]
        command += ["python", str(script),
                    "--model", str(model_path(config, args.model_root, "asr")),
                    "--host", service["host"], "--port", str(service["port"]),
                    "--gpu-memory-utilization", str(service["gpu_memory_utilization"]),
                    "--max-new-tokens", str(service["max_new_tokens"]),
                    "--chunk-size-sec", str(stream["chunk_size_sec"]),
                    "--unfixed-chunk-num", str(stream["unfixed_chunk_num"]),
                    "--unfixed-token-num", str(stream["unfixed_token_num"])]
    elif role == "llm":
        command += ["vllm", "serve", str(model_path(config, args.model_root, "llm")),
                    "--host", service["host"], "--port", str(service["port"]),
                    "--served-model-name", service["served_model_name"],
                    "--max-model-len", str(service["max_model_len"]),
                    "--gpu-memory-utilization", str(service["gpu_memory_utilization"]),
                    "--quantization", service["quantization"]]
    elif role == "turn_detector":
        # Standalone audio-based TurnSense ONNX HTTP service (vendored under
        # scripts/remote/turnsense). Not vLLM: it reads the raw PCM buffered by
        # the X-Talk TurnSense adapter and returns complete/incomplete/invalid.
        source_dir = Path(__file__).with_name("turnsense").resolve()
        onnx_path = (args.model_root / service["onnx_file"]).resolve()
        cmvn_path = (args.model_root / service["cmvn_file"]).resolve()
        required = {
            "service.py": source_dir / "service.py",
            "infer.py": source_dir / "infer.py",
            "frontend/audio_frontend.py": source_dir / "frontend" / "audio_frontend.py",
            "onnx": onnx_path,
            "cmvn": cmvn_path,
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        if missing:
            raise ValueError(f"missing TurnSense assets: {missing}")
        # XTALK_TURNSENSE_PYTHON launches the vendored server with an explicit
        # interpreter (used when the turnsense conda env is not baked into the
        # container image); otherwise fall back to the configured conda env.
        python_override = os.environ.get("XTALK_TURNSENSE_PYTHON")
        command = [python_override] if python_override else command + ["python"]
        command += [str(source_dir / "service.py"),
                    "--host", service["host"], "--port", str(service["port"]),
                    "--onnx-path", str(onnx_path), "--cmvn-file", str(cmvn_path),
                    "--clip-mode", service.get("clip_mode", "tail"),
                    "--max-concurrency", str(service.get("max_concurrency", 8)),
                    "--max-workers", str(service.get("max_workers", 4))]
        if service.get("use_cuda"):
            command.append("--use-cuda")
        os.chdir(source_dir)
    else:
        roots = {
            "moss_service": Path(os.environ["XTALK_MOSS_SERVICE_ROOT"]).resolve(),
            "moss_source": Path(os.environ["XTALK_MOSS_SOURCE_ROOT"]).resolve(),
        }
        for source, root in roots.items():
            commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            if commit != config["sources"][source]["commit"]:
                raise ValueError(f"Unexpected {source} source commit: {commit}")
            subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD"], check=True)
        entrypoint = roots["moss_service"] / "serving/fast_api_entrypoint.py"
        if not entrypoint.is_file():
            raise ValueError(f"Missing MOSS service entrypoint: {entrypoint}")
        os.environ["MOSS_TTS_UPSTREAM_DIR"] = str(roots["moss_source"])
        torch_compile = service.get("torch_compile", "default")
        if torch_compile == "disable":
            # Eager fallback: no per-shape recompilation but far slower than
            # real time.  Kept for debugging only.
            os.environ["TORCH_COMPILE_DISABLE"] = "1"
            os.environ["TORCHDYNAMO_DISABLE"] = "1"
        elif torch_compile == "dynamic":
            # Make dynamo treat shapes as dynamic so one compilation serves any
            # prefill length instead of recompiling per response length.
            patch_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "ic_moss_patch"
            patch_dir.mkdir(parents=True, exist_ok=True)
            (patch_dir / "sitecustomize.py").write_text(
                "import torch._dynamo as _dynamo\n"
                "_dynamo.config.assume_static_by_default = False\n"
                "_dynamo.config.dynamic_shapes = True\n"
                "_dynamo.config.cache_size_limit = max("
                "getattr(_dynamo.config, 'cache_size_limit', 64), 256)\n",
                encoding="utf-8",
            )
            existing = os.environ.get("PYTHONPATH", "")
            os.environ["PYTHONPATH"] = str(patch_dir) + (
                os.pathsep + existing if existing else ""
            )
        os.chdir(roots["moss_service"])
        tts = str(model_path(config, args.model_root, "tts"))
        command += ["python", str(entrypoint), "--host", service["host"],
                    "--port", str(service["port"]), "--device", "cuda:0",
                    "--attn_impl", service["attn_impl"],
                    "--target_sr", str(service["output_sample_rate"]),
                    "--model_path", tts, "--tokenizer_path", tts,
                    "--codec_model_path", str(model_path(config, args.model_root, "codec"))]
    os.execvp(command[0], command)


def main() -> None:
    """Dispatch model preparation, independent smoke tests, or service launch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download")
    asr = commands.add_parser("asr-smoke")
    asr.add_argument("--audio", type=Path, required=True)
    asr.add_argument("--output", type=Path, required=True)
    asr.add_argument("--chunk-seconds", type=float)
    asr.add_argument("--gpu-index", type=int)
    tts = commands.add_parser("tts-smoke")
    tts.add_argument("--reference", type=Path, required=True)
    tts.add_argument("--output", type=Path, required=True)
    tts.add_argument("--url")
    tts.add_argument("--gap-seconds", type=float, default=1.0)
    tts.add_argument("--timeout-seconds", type=float, default=900)
    tts.add_argument("--text", action="append", default=None)
    tts.add_argument("--stream-chunk-words", type=int, default=0,
                     help="split each --text into N-word chunks pushed incrementally (0 = off)")
    deps = commands.add_parser("check-deps")
    deps.add_argument(
        "--role", choices=("asr", "llm", "turn_detector", "tts"), required=True
    )
    server = commands.add_parser("serve")
    server.add_argument("service", choices=("asr", "llm", "turn_detector", "tts"))
    server.add_argument("--gpu-index", type=int)
    args = parser.parse_args()
    args.config = args.config.resolve()
    args.model_root = args.model_root.resolve()
    config = read_config(args.config)
    if args.command == "download":
        download_models(config, args.model_root)
    elif args.command == "asr-smoke":
        select_gpu(config["services"]["asr"]["gpu_index"] if args.gpu_index is None else args.gpu_index)
        asr_smoke(config, args)
    elif args.command == "tts-smoke":
        args.text = args.text or ["你好，我们正在检查这套语音系统的流式输出。", "请把会议安排在下周三下午三点。", "如果需要修改时间，可以随时告诉我。"]
        asyncio.run(asyncio.wait_for(tts_smoke(config, args), timeout=args.timeout_seconds))
    elif args.command == "check-deps":
        report = check_dependencies(config, args.role)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            raise SystemExit(f"dependencies for role {args.role!r} do not match the config")
    else:
        serve(config, args)


if __name__ == "__main__":
    main()
