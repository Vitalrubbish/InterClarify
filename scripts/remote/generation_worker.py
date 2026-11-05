"""Serve a single offline Qwen or IndexTTS backend over a private local socket."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import socketserver
import struct
import sys
import threading
import time
import traceback


def receive(stream, count):
    blocks = []
    while count:
        block = stream.recv(count)
        if not block:
            raise ConnectionError("Socket closed before the message ended")
        blocks.append(block)
        count -= len(block)
    return b"".join(blocks)


def request(path: str, payload: dict, timeout: float = 90) -> dict:
    import socket

    data = json.dumps(payload).encode()
    if len(data) > 1024 * 1024:
        raise ValueError("Request exceeds one MiB")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(struct.pack("!I", len(data)) + data)
        size = struct.unpack("!I", receive(connection, 4))[0]
        if size > 1024 * 1024:
            raise ValueError("Response exceeds one MiB")
        result = json.loads(receive(connection, size))
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def request_stream(path: str, payload: dict, timeout: float = 90):
    import socket

    data = json.dumps({**payload, "stream": True}).encode()
    if len(data) > 1024 * 1024:
        raise ValueError("Request exceeds one MiB")
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(struct.pack("!I", len(data)) + data)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Streaming generation exceeded its request budget")
            connection.settimeout(remaining)
            size = struct.unpack("!I", receive(connection, 4))[0]
            if size > 1024 * 1024:
                raise ValueError("Response exceeds one MiB")
            event = json.loads(receive(connection, size))
            if event.get("id") != payload["id"]:
                raise ValueError("Streaming response request ID mismatch")
            if event.get("event") == "error":
                raise RuntimeError(event["error"])
            if event.get("event") not in {"text_delta", "done"}:
                raise ValueError("Unknown streaming response event")
            yield event
            if event["event"] == "done":
                return


class Backend:
    def __init__(self, args):
        import torch
        import numpy as np

        self.args, self.torch, self.np = args, torch, np
        self.lock = threading.Lock()
        self.events_lock = threading.Lock()
        self.cancelled = set()
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError("One scheduler-assigned GPU is required per backend")
        if "4090" not in torch.cuda.get_device_name(0):
            raise RuntimeError("RTX 4090 is required for this configuration")
        torch.cuda.set_per_process_memory_fraction(args.memory_fraction, 0)
        if args.backend == "qwen":
            from transformers import AutoModelForCausalLM, AutoTokenizer

            path = args.root / "models/qwen2.5-7b-instruct"
            self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                path, torch_dtype=torch.bfloat16, device_map="cuda:0", local_files_only=True).eval()
            with torch.inference_mode():
                self.generate({"id": "warmup", "messages": [{"role": "user", "content": "Say hello."}],
                               "max_new_tokens": 8, "seed": 42})
        else:
            sys.path.insert(0, str(args.upstream / "indextts-1.5"))
            from indextts.infer import IndexTTS

            path = args.root / "models/indextts-1.5"
            self.model = IndexTTS(cfg_path=str(path / "config.yaml"), model_dir=str(path),
                                  device="cuda:0", is_fp16=True, use_cuda_kernel=False)
            self.generate({"id": "warmup", "text": "Hello, I am ready.", "seed": 42})

    def is_cancelled(self, identifier):
        with self.events_lock:
            return identifier in self.cancelled

    def dispatch(self, payload, emit=None):
        identifier = payload.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier):
            raise ValueError("Invalid request ID")
        if payload.get("operation") == "cancel":
            with self.events_lock:
                if len(self.cancelled) >= 10000:
                    raise RuntimeError("Cancellation registry exceeds the run budget")
                self.cancelled.add(identifier)
            return {"cancelled": True}
        with self.lock:
            if self.is_cancelled(identifier):
                return {"cancelled": True}
            return self.generate(payload, emit)

    def generate(self, payload, emit=None):
        torch, np = self.torch, self.np
        identifier = payload["id"]
        seed = int(payload.get("seed", 42))
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)
        started = time.monotonic()
        with torch.inference_mode():
            if self.args.backend == "qwen":
                from transformers import StoppingCriteria, StoppingCriteriaList, TextStreamer

                backend = self

                class Cancelled(StoppingCriteria):
                    def __call__(self, input_ids, scores, **kwargs):
                        return backend.is_cancelled(identifier)

                class Streamer(TextStreamer):
                    def on_finalized_text(self, text, stream_end=False):
                        if text:
                            emit({"id": identifier, "event": "text_delta", "text": text,
                                  "emitted_at": time.monotonic()})

                text = self.tokenizer.apply_chat_template(payload["messages"], tokenize=False,
                                                          add_generation_prompt=True)
                inputs = self.tokenizer(text, return_tensors="pt").to("cuda:0")
                if inputs.input_ids.shape[1] > 4096:
                    raise ValueError("Conversation exceeds the frozen 4096 token budget")
                options = {"streamer": Streamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)} if emit else {}
                tokens = self.model.generate(**inputs, max_new_tokens=min(int(payload.get("max_new_tokens", 128)), 128),
                                             do_sample=False, stopping_criteria=StoppingCriteriaList([Cancelled()]),
                                             **options)
                result = {"text": self.tokenizer.decode(tokens[0, inputs.input_ids.shape[1]:],
                                                         skip_special_tokens=True)}
            else:
                if not payload["text"].strip() or len(payload["text"]) > 600:
                    raise ValueError("TTS segment is empty or exceeds 600 characters")
                target = self.args.output / f"{identifier}.wav"
                method = getattr(self.args, "tts_inference_method", "infer")
                beams = getattr(self.args, "tts_num_beams", 3)
                inference = getattr(self.model, method)
                inference(audio_prompt=str(self.args.voice), text=payload["text"],
                                 output_path=str(target), verbose=False, max_mel_tokens=600,
                                 do_sample=True, top_p=0.8, top_k=30, temperature=1.0, num_beams=beams)
                result = {"audio": str(target), "tts_inference_method": method, "tts_num_beams": beams}
        torch.cuda.synchronize()
        result.update(cancelled=self.is_cancelled(identifier), started_at=started,
                      finished_at=time.monotonic(), seed=seed)
        return result


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("qwen", "indextts"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--voice", type=Path)
    parser.add_argument("--memory-fraction", type=float, default=0.83)
    parser.add_argument("--tts-inference-method", choices=("infer", "infer_fast"), default="infer")
    parser.add_argument("--tts-num-beams", type=int, choices=(1, 3), default=3)
    args = parser.parse_args()
    if not 0 < args.memory_fraction <= 0.83:
        parser.error("Memory fraction must be in (0, 0.83]")
    if not (Path(sys.prefix) / "conda-meta/history").is_file():
        parser.error("Use conda Python")
    args.output.mkdir(parents=True, exist_ok=False)
    backend = Backend(args)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(120)
            payload = {}

            def send(result):
                data = json.dumps(result).encode()
                if len(data) > 1024 * 1024:
                    raise ValueError("Response exceeds one MiB")
                self.request.sendall(struct.pack("!I", len(data)) + data)

            try:
                size = struct.unpack("!I", receive(self.request, 4))[0]
                if size > 1024 * 1024:
                    raise ValueError("Request exceeds one MiB")
                payload = json.loads(receive(self.request, size))
                streaming = bool(payload.get("stream"))
                result = backend.dispatch(payload, send if streaming else None)
                if streaming:
                    result = {"id": payload["id"], "event": "done", **result}
            except Exception as exc:
                traceback.print_exc()
                result = {"error": f"{type(exc).__name__}: {exc}"}
                if payload.get("stream"):
                    result.update(id=payload.get("id"), event="error")
            send(result)

    with Server(str(args.socket), Handler) as server:
        args.socket.chmod(0o600)
        ready = {"backend": args.backend, "socket": str(args.socket), "python": sys.prefix,
                 "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 "ready_at": time.monotonic(), "voice": str(args.voice),
                 "tts_inference_method": args.tts_inference_method, "tts_num_beams": args.tts_num_beams}
        (args.output / "ready.json").write_text(json.dumps(ready, indent=2) + "\n")
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
