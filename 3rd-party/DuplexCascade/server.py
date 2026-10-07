#!/usr/bin/env python3


from __future__ import annotations

import argparse
import asyncio
import http
import inspect
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import msgpack  # type: ignore
import numpy as np
import torch
import websockets
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

try:
    from safetensors.torch import load_file as load_safetensors_file

    _HAS_SAFETENSORS = True
except Exception:
    _HAS_SAFETENSORS = False
    load_safetensors_file = None

# Ensure local imports work when running `python server.py`.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
WEB_ROOT = PROJECT_ROOT / "web"

from model import Model


SPECIAL_TOKENS = [
    "<|no voice|>",
    "<|user is talking|>",
    "<|user finish talking|>",
    "<|user is thinking|>",
    "<|user interruption|>",
    "<|user backchannel|>",
]


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_model_state_dict(repo_dir: Path) -> Dict[str, torch.Tensor]:
    safetensors_path = repo_dir / "model_state.safetensors"
    pt_path = repo_dir / "model_state.pt"
    bin_path = repo_dir / "pytorch_model.bin"

    if safetensors_path.exists():
        if not _HAS_SAFETENSORS or load_safetensors_file is None:
            raise RuntimeError(
                "Found `model_state.safetensors` but `safetensors` is not installed."
            )
        return load_safetensors_file(str(safetensors_path), device="cpu")

    if pt_path.exists():
        state = torch.load(str(pt_path), map_location="cpu")
        if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
            return state["model"]
        if isinstance(state, dict):
            return state
        raise ValueError("`model_state.pt` must contain a dict state_dict.")

    if bin_path.exists():
        state = torch.load(str(bin_path), map_location="cpu")
        if isinstance(state, dict):
            return state
        raise ValueError("`pytorch_model.bin` must contain a dict state_dict.")

    raise FileNotFoundError(
        f"No model state file found in {repo_dir}. "
        "Expected one of: model_state.safetensors, model_state.pt, pytorch_model.bin."
    )


def _build_tts_ws_url(base_ws_url: str, voice: str, api_key_qs: Optional[str]) -> str:
    """
    Ensure TTS ws URL has voice + format params.
    base example: ws://127.0.0.1:8081/api/tts_streaming
    """
    u = urlparse(base_ws_url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q.setdefault("format", "PcmMessagePack")
    if voice:
        q["voice"] = voice
    if api_key_qs:
        # For clients that cannot set headers; harmless if server ignores.
        q.setdefault("auth_id", api_key_qs)
    u2 = u._replace(query=urlencode(q))
    return urlunparse(u2)


async def _ws_connect(url: str, headers: dict) -> websockets.WebSocketClientProtocol:
    """
    websockets has changed the header parameter name across versions:
    - newer: additional_headers
    - older/legacy: extra_headers
    This helper picks the correct one at runtime.
    """
    sig = inspect.signature(websockets.connect)
    kwargs = {}
    if headers:
        if "additional_headers" in sig.parameters:
            kwargs["additional_headers"] = headers
        elif "extra_headers" in sig.parameters:
            kwargs["extra_headers"] = headers
        else:
            raise RuntimeError(
                "Unsupported websockets.connect signature; cannot pass auth headers."
            )
    return await websockets.connect(url, **kwargs)


class KyutaiBridgeServer:
    def __init__(
        self,
        *,
        llm_model: Model,
        tokenizer: Any,
        llm_device: str,
        kyutai_stt_ws: str,
        kyutai_tts_ws: str,
        kyutai_api_key: str,
        kyutai_tts_voice: str,
        overlap_window_s: float,
        max_new_tokens: int,
        stt_pre_silence_s: float = 0.0,
    ) -> None:
        self.llm = llm_model
        self.tokenizer = tokenizer
        self.llm_device = torch.device(llm_device)

        self.doc_root = str(WEB_ROOT.resolve())

        self.kyutai_stt_ws = kyutai_stt_ws
        self.kyutai_tts_ws_base = kyutai_tts_ws
        self.kyutai_api_key = kyutai_api_key
        self.kyutai_tts_voice = kyutai_tts_voice
        self.overlap_window_s = float(overlap_window_s)
        self.max_new_tokens = int(max_new_tokens)
        self.stt_pre_silence_s = float(stt_pre_silence_s)

        self.prepare_llm_tokens()

    def prepare_llm_tokens(self) -> None:
        def get_ids(text: str) -> list[int]:
            return self.tokenizer.encode(text, add_special_tokens=False)

        self.bos_id = self.tokenizer.bos_token_id
        # Qwen2 ChatML-like template (align with tomoshi_qwen/dataset/ultrachat.py)
        self.header_user = get_ids("<|im_start|>user\n")
        self.header_assist = get_ids("<|im_start|>assistant\n")
        self.im_end_ids = get_ids("<|im_end|>")
        self.im_end_id = self.im_end_ids[0] if self.im_end_ids else self.tokenizer.eos_token_id
        self.im_end_nl_ids = get_ids("<|im_end|>\n") or list(self.im_end_ids)
        self.nl_ids = get_ids("\n")

        # user silence token used in prompt
        self.no_voice_ids = get_ids("<|no voice|>")

        # assistant special tokens (v3)
        special_texts = [
            "<|user is talking|>",
            "<|user finish talking|>",
            "<|user is thinking|>",
            "<|user interruption|>",
            "<|user backchannel|>",
        ]
        self.special_token_ids: set[int] = set()
        self.special_id_to_text: dict[int, str] = {}
        for s in special_texts:
            for tid in get_ids(s):
                self.special_token_ids.add(int(tid))
                self.special_id_to_text[int(tid)] = s

        # When decoding assistant normal text, skip these token ids (plus <|no voice|>)
        self.skip_for_text: set[int] = set(self.special_token_ids)
        for tid in self.no_voice_ids:
            self.skip_for_text.add(int(tid))
        # Also skip ChatML control tokens if they appear
        for tid in self.header_user + self.header_assist + list(self.im_end_nl_ids) + list(self.im_end_ids) + list(self.nl_ids):
            self.skip_for_text.add(int(tid))

    def filter_period_for_tts(self, text: str) -> str:
        """Remove period (.) from text for TTS, but keep it for frontend display."""
        return text.replace(".", "")

    async def process_request(
        self, path: str, request_headers: websockets.Headers
    ) -> Optional[Tuple[http.HTTPStatus, websockets.Headers, bytes]]:
        if "sec-websocket-key" not in (
            request_headers.headers if hasattr(request_headers, "headers") else request_headers
        ):
            # Normal HTTP: serve static files from doc_root
            if path == "/":
                path = "/index.html"
            rel = path.lstrip("/")
            fs_path = os.path.join(self.doc_root, rel)
            if not os.path.isfile(fs_path):
                return http.HTTPStatus.NOT_FOUND, {"Content-Type": "text/plain; charset=utf-8"}, b"Not found"

            ext = os.path.splitext(fs_path)[1].lower()
            mime = "application/octet-stream"
            if ext == ".html":
                mime = "text/html; charset=utf-8"
            elif ext == ".css":
                mime = "text/css; charset=utf-8"
            elif ext == ".js":
                mime = "application/javascript; charset=utf-8"
            elif ext == ".json":
                mime = "application/json; charset=utf-8"
            elif ext == ".png":
                mime = "image/png"
            elif ext in [".jpg", ".jpeg"]:
                mime = "image/jpeg"
            elif ext == ".svg":
                mime = "image/svg+xml"

            with open(fs_path, "rb") as f:
                data = f.read()
            return http.HTTPStatus.OK, {"Content-Type": mime}, data

        return None

    async def run(self, port: int) -> None:
        print(f"[DuplexCascade] Server listening on 0.0.0.0:{int(port)}", flush=True)
        async with websockets.serve(
            self.handle_connection,
            host="",
            port=port,
            max_size=8 << 20,
            max_queue=32,
            process_request=self.process_request,
        ):
            await asyncio.Future()

    async def handle_connection(self, ws: websockets.WebSocketServerProtocol) -> None:
        try:
            await self.handle_connection_impl(ws)
        except websockets.exceptions.ConnectionClosedError:
            return
        except Exception:
            return

    async def handle_connection_impl(self, ws: websockets.WebSocketServerProtocol) -> None:
        send_lock = asyncio.Lock()

        async def send_json(obj: Dict[str, Any]) -> None:
            async with send_lock:
                await ws.send(json.dumps(obj, ensure_ascii=False))

        async def send_pcm_f32le(pcm: np.ndarray) -> None:
            if pcm is None:
                return
            pcm = np.asarray(pcm, dtype=np.float32)
            if pcm.ndim != 1:
                pcm = pcm.reshape(-1)
            async with send_lock:
                await ws.send(pcm.astype("<f4", copy=False).tobytes())

        async def send_audio_control(action: str, reason: str = "") -> None:
            payload: Dict[str, Any] = {"type": "audio_control", "action": str(action)}
            if reason:
                payload["reason"] = str(reason)
            await send_json(payload)

        # Browser->server queues
        audio_q: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=64)
        ctrl_q: asyncio.Queue[str] = asyncio.Queue(maxsize=8)  # "reset" / "done"

        async def browser_rx_task() -> None:
            try:
                async for msg in ws:
                    if isinstance(msg, str):
                        s = msg.strip()
                        if s == "Reset":
                            await ctrl_q.put("reset")
                        elif s == "Done":
                            await ctrl_q.put("done")
                            return
                        else:
                            # ignore unknown text
                            continue
                    else:
                        # bytes: float32 PCM mono (24k) from browser
                        if not msg:
                            continue
                        pcm = np.frombuffer(msg, dtype="<f4").astype(np.float32, copy=False)
                        if pcm.size == 0:
                            continue
                        # best-effort backpressure: drop oldest if queue full
                        if audio_q.full():
                            try:
                                _ = audio_q.get_nowait()
                            except Exception:
                                pass
                        await audio_q.put(pcm)
            except websockets.exceptions.ConnectionClosed:
                return

        browser_rx = asyncio.create_task(browser_rx_task())

        # Per-session loop (restart on Reset)
        while True:
            # Drain any pending audio to avoid mixing sessions
            while not audio_q.empty():
                try:
                    audio_q.get_nowait()
                except Exception:
                    break

            # Conversation state
            history_ids: list[int] = []
            if self.bos_id is not None:
                history_ids.append(int(self.bos_id))

            # Event to signal first text received
            first_text_received_event = asyncio.Event()
            asr_buffer_words: list[str] = []
            asr_buffer_lock = asyncio.Lock()

            # Kyutai STT connection
            headers = {}
            if self.kyutai_api_key:
                headers["kyutai-api-key"] = self.kyutai_api_key

            stt_ws = await _ws_connect(self.kyutai_stt_ws, headers=headers)

            # Optional pre-silence (required by some models, e.g. 2.6B)
            if self.stt_pre_silence_s > 0:
                n = int(24000 * self.stt_pre_silence_s)
                silence = [0.0] * n
                stt_msg = {"type": "Audio", "pcm": silence}
                await stt_ws.send(msgpack.packb(stt_msg, use_bin_type=True, use_single_float=True))

            # --- TTS Client Management ---
            class TTSClient:
                def __init__(self_obj):
                    self_obj.ws = None
                    self_obj.rx_task = None
                    self_obj.lock = asyncio.Lock()
                    
                async def connect(self_obj):
                    # Ensure closed first
                    await self_obj.close_internal()
                    
                    tts_url = _build_tts_ws_url(
                        self.kyutai_tts_ws_base,
                        voice=self.kyutai_tts_voice,
                        api_key_qs=(self.kyutai_api_key or None),
                    )
                    try:
                        self_obj.ws = await _ws_connect(tts_url, headers=headers)
                        self_obj.rx_task = asyncio.create_task(self_obj.rx_loop(self_obj.ws))
                    except Exception:
                        self_obj.ws = None
                        self_obj.rx_task = None

                async def close_internal(self_obj):
                    if self_obj.rx_task:
                        self_obj.rx_task.cancel()
                        try:
                            await self_obj.rx_task
                        except: pass
                        self_obj.rx_task = None
                    if self_obj.ws:
                        try:
                            await self_obj.ws.close()
                        except: pass
                        self_obj.ws = None

                async def reset(self_obj, reason=""):
                    async with self_obj.lock:
                        await send_audio_control("stop", reason=reason)
                        await self_obj.close_internal()
                        await self_obj.connect()

                async def send_text(self_obj, text, send_eos=False):
                    async with self_obj.lock:
                        if self_obj.ws is None:
                            await self_obj.connect()
                        if self_obj.ws:
                            try:
                                # Send text
                                payload = msgpack.packb({"type": "Text", "text": text}, use_bin_type=True)
                                await self_obj.ws.send(payload)
                                if send_eos:
                                    await self_obj.ws.send(msgpack.packb({"type": "Eos"}, use_bin_type=True))
                            except Exception:
                                # If send fails, maybe connection is dead. Reset.
                                await self_obj.close_internal()
                                await self_obj.connect()

                async def send_eos(self_obj):
                    async with self_obj.lock:
                        if self_obj.ws:
                            try:
                                await self_obj.ws.send(msgpack.packb({"type": "Eos"}, use_bin_type=True))
                            except Exception:
                                await self_obj.close_internal()
                                await self_obj.connect()

                async def rx_loop(self_obj, ws_ref):
                    try:
                        async for msg_bytes in ws_ref:
                            try:
                                msg = msgpack.unpackb(msg_bytes, raw=False)
                                if msg.get("type") == "Audio":
                                    pcm = np.asarray(msg.get("pcm", []), dtype=np.float32)
                                    if pcm.size:
                                        await send_pcm_f32le(pcm)
                            except Exception:
                                continue
                    except Exception:
                        pass
            
            tts_client = TTSClient()
            # User requested initial connection
            await tts_client.connect()
            
            tts_speaking_flag = 0
            tts_thinking_flag = 0

            async def stt_sender_task() -> None:
                try:
                    while True:
                        pcm = await audio_q.get()
                        if pcm is None:
                            return
                        # Send in chunks of 1920 samples (80ms @24k)
                        offset = 0
                        while offset < pcm.size:
                            chunk = pcm[offset : offset + 1920]
                            offset += 1920
                            if chunk.size == 0:
                                continue
                            stt_msg = {"type": "Audio", "pcm": [float(x) for x in chunk]}
                            packed = msgpack.packb(stt_msg, use_bin_type=True, use_single_float=True)
                            await stt_ws.send(packed)
                        audio_q.task_done()
                except websockets.exceptions.ConnectionClosed:
                    return

            async def stt_receiver_task() -> None:
                words: list[str] = []
                try:
                    async for msg_bytes in stt_ws:
                        msg = msgpack.unpackb(msg_bytes, raw=False)
                        if not isinstance(msg, dict):
                            continue
                        t = msg.get("type")
                        if t == "Word":
                            w = str(msg.get("text", "")).strip()
                            if w:
                                words.append(w)
                                async with asr_buffer_lock:
                                    asr_buffer_words.append(w)
                                current_asr_text = " ".join(words)
                                first_text_received_event.set()
                                await send_json({"type": "user_asr", "text": current_asr_text})
                        # ignore Step / EndWord / Marker for now (but keep robust)
                except websockets.exceptions.ConnectionClosed:
                    return
                except Exception:
                    return

            # Streaming helper
            try:
                from transformers.generation.streamers import BaseStreamer
            except ImportError:
                class BaseStreamer:  # type: ignore
                    def put(self, value): pass
                    def end(self): pass

            class TokenQueueStreamer(BaseStreamer):
                def __init__(self, q: queue.Queue):
                    self.q = q
                    self.stop_signal = object()
                    self.prompt_skipped = False

                def put(self, value):
                    if not self.prompt_skipped:
                        # transformers will stream the full prompt first; skip it
                        if value.numel() > 1:
                            self.prompt_skipped = True
                            return
                        self.prompt_skipped = True
                    if value.ndim > 1:
                        value = value.flatten()
                    for v in value:
                        self.q.put(v.item())

                def end(self):
                    self.q.put(self.stop_signal)

            async def llm_tick_task() -> None:
                nonlocal tts_speaking_flag, tts_thinking_flag
                
                # Wait for first user text to start the clock
                await first_text_received_event.wait()
                next_tick_time = time.time() + self.overlap_window_s

                try:
                    while True:
                        now = time.time()
                        sleep_dur = next_tick_time - now
                        if sleep_dur > 0:
                            await asyncio.sleep(sleep_dur)
                        else:
                            # If lagging, yield briefly
                            await asyncio.sleep(0.001)

                        # Schedule next tick (punctual)
                        next_tick_time = max(time.time(), next_tick_time + self.overlap_window_s)

                        # Delta text since last tick
                        async with asr_buffer_lock:
                            if asr_buffer_words:
                                delta_text = " ".join(asr_buffer_words)
                                asr_buffer_words.clear()
                            else:
                                delta_text = ""

                        # user micro-turn
                        history_ids.extend(self.header_user)
                        if delta_text.strip():
                            history_ids.extend(self.tokenizer.encode(delta_text, add_special_tokens=False))
                        else:
                            history_ids.extend(self.no_voice_ids)
                        history_ids.extend(self.im_end_nl_ids)

                        # assistant header
                        history_ids.extend(self.header_assist)

                        input_tensor = torch.tensor([history_ids], dtype=torch.long, device=self.llm_device)
                        attn_mask = torch.ones_like(input_tensor)

                        # Streaming Generation Setup
                        token_q: queue.Queue = queue.Queue()
                        streamer = TokenQueueStreamer(token_q)

                        def run_generation():
                            try:
                                with torch.no_grad():
                                    self.llm.generate(
                                        input_ids=input_tensor,
                                        attention_mask=attn_mask,
                                        max_new_tokens=self.max_new_tokens,
                                        eos_token_id=self.im_end_id,
                                        pad_token_id=self.im_end_id,
                                        do_sample=False,
                                        streamer=streamer,
                                    )
                            except Exception:
                                pass
                            finally:
                                streamer.end()

                        # Start generation in thread
                        gen_thread = threading.Thread(target=run_generation)
                        gen_thread.start()

                        # Consume stream
                        pending_text_ids: list[int] = []
                        previous_decoded_text = ""
                        tts_text_buffer = ""

                        async def flush_tts_buffer(send_eos: bool = False) -> None:
                            nonlocal tts_text_buffer
                            if tts_text_buffer:
                                await tts_client.send_text(tts_text_buffer, send_eos=send_eos)
                            elif send_eos:
                                await tts_client.send_eos()
                            tts_text_buffer = ""
                        
                        while True:
                            try:
                                # Non-blocking poll
                                item = token_q.get_nowait()
                            except queue.Empty:
                                if not gen_thread.is_alive():
                                    break
                                await asyncio.sleep(0.01)
                                continue

                            if item is streamer.stop_signal:
                                break
                            
                            tid_i = int(item)
                            history_ids.append(tid_i)
                            
                            # Check if special
                            if tid_i in self.special_token_ids:
                                s_text = self.special_id_to_text.get(tid_i, str(tid_i))
                                send_eos = False
                                send_eos_if_empty = False
                                if s_text == "<|assistant_backchannel|>":
                                    send_eos = True
                                if s_text == "<|user is thinking|>" and tts_thinking_flag == 0:
                                    send_eos = True
                                    send_eos_if_empty = True
                                
                                # Flush pending text before special token
                                if pending_text_ids:
                                    full_text = self.tokenizer.decode(pending_text_ids, skip_special_tokens=True)
                                    chunk_text = full_text[len(previous_decoded_text):]
                                    if chunk_text:
                                        await send_json({"type": "assistant_text", "text": chunk_text})
                                        # Filter out period for TTS, but keep it for frontend display
                                        tts_text_buffer += self.filter_period_for_tts(chunk_text)
                                    
                                    pending_text_ids = []
                                    previous_decoded_text = ""
                                if send_eos and not send_eos_if_empty and not tts_text_buffer:
                                    send_eos = False
                                await flush_tts_buffer(send_eos=send_eos)

                                await send_json({"type": "assistant_special", "text": s_text})
                                
                                # Handle TTS control based on special tokens
                                if s_text == "<|user finish talking|>":
                                    tts_speaking_flag = 1
                                    tts_thinking_flag = 0
                                elif s_text == "<|user is thinking|>":
                                    if tts_thinking_flag == 0:
                                        tts_thinking_flag = 1
                                elif s_text in ("<|user interruption|>", "<|user is talking|>"):
                                    if tts_speaking_flag == 1:
                                        # Immediate reset
                                        await tts_client.reset(reason=s_text)
                                        tts_speaking_flag = 0

                            elif tid_i in self.skip_for_text:
                                # Just skip (e.g. ChatML tokens), but flush pending if it's an end token
                                if tid_i in self.im_end_ids or tid_i in self.im_end_nl_ids:
                                    if pending_text_ids:
                                        full_text = self.tokenizer.decode(pending_text_ids, skip_special_tokens=True)
                                        chunk_text = full_text[len(previous_decoded_text):]
                                        if chunk_text:
                                            await send_json({"type": "assistant_text", "text": chunk_text})
                                            # Filter out period for TTS, but keep it for frontend display
                                            tts_text_buffer += self.filter_period_for_tts(chunk_text)
                                    pending_text_ids = []
                                    previous_decoded_text = ""
                                    await flush_tts_buffer(send_eos=False)
                                continue
                            else:
                                # Normal text token
                                pending_text_ids.append(tid_i)
                                
                                # Stream output logic:
                                # Decode full pending buffer, subtract what we already sent.
                                full_text = self.tokenizer.decode(pending_text_ids, skip_special_tokens=True)
                                chunk_text = full_text[len(previous_decoded_text):]
                                
                                if chunk_text:
                                    # Send incremental text
                                    await send_json({"type": "assistant_text", "text": chunk_text})
                                    # Filter out period for TTS, but keep it for frontend display
                                    tts_text_buffer += self.filter_period_for_tts(chunk_text)
                                    previous_decoded_text = full_text

                                await flush_tts_buffer(send_eos=False)

                        gen_thread.join()
                        
                except asyncio.CancelledError:
                    return
                except Exception:
                    return

            stt_sender = asyncio.create_task(stt_sender_task())
            stt_receiver = asyncio.create_task(stt_receiver_task())
            llm_tick = asyncio.create_task(llm_tick_task())

            # Wait for control signal or browser disconnect
            reset_or_done: Optional[str] = None
            try:
                while True:
                    if browser_rx.done():
                        reset_or_done = "done"
                        break
                    try:
                        reset_or_done = await asyncio.wait_for(ctrl_q.get(), timeout=0.2)
                        break
                    except asyncio.TimeoutError:
                        continue
            finally:
                # tear down session tasks
                for t in (stt_sender, stt_receiver, llm_tick):
                    t.cancel()
                
                # Close TTS client
                await tts_client.close_internal()
                
                try:
                    await stt_ws.close()
                except Exception:
                    pass
                await asyncio.gather(stt_sender, stt_receiver, llm_tick, return_exceptions=True)

            if reset_or_done == "reset":
                # also clear UI (best-effort)
                try:
                    await send_json({"type": "user_asr", "text": ""})
                    await send_json({"type": "assistant_text", "text": ""})
                    await send_json({"type": "assistant_special", "text": ""})
                except Exception:
                    pass
                continue

            # done / disconnect
            break

        # Close browser RX
        try:
            browser_rx.cancel()
            await asyncio.gather(browser_rx, return_exceptions=True)
        except Exception:
            pass


def get_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=31606)
    p.add_argument("--hf-repo-id", type=str, default="sbintuitions/DuplexCascade", help="Hugging Face model repo id")
    p.add_argument("--hf-revision", type=str, default="main", help="Hugging Face repo revision")
    p.add_argument("--hf-token", type=str, default=None, help="Hugging Face token (optional)")
    p.add_argument("--llm-device", type=str, default=("cuda" if torch.cuda.is_available() else "cpu"))
    p.add_argument("--max-new-tokens", type=int, default=64)
    p.add_argument("--overlap-window-s", type=float, default=0.6)

    p.add_argument("--kyutai-stt-ws", type=str, default="ws://127.0.0.1:31607/api/asr-streaming", help="e.g. ws://127.0.0.1:31607/api/asr-streaming")
    p.add_argument("--kyutai-tts-ws", type=str, default="ws://127.0.0.1:31608/api/tts_streaming", help="e.g. ws://127.0.0.1:31608/api/tts_streaming")
    p.add_argument("--kyutai-api-key", type=str, default="public_token")
    p.add_argument("--kyutai-tts-voice", type=str, default="expresso/ex03-ex01_happy_001_channel1_334s.wav")
    p.add_argument("--stt-pre-silence-s", type=float, default=0.0, help="Send initial silence to STT (e.g. 1.0 for some models)")
    return p.parse_args()


def main() -> None:
    args = get_args()
    repo_dir = Path(
        snapshot_download(
            repo_id=args.hf_repo_id,
            repo_type="model",
            revision=args.hf_revision,
            token=args.hf_token,
        )
    )

    cfg_path = repo_dir / "train_cfg.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"`train_cfg.json` not found in HF repo snapshot: {repo_dir}")

    cfg = _read_json(cfg_path)
    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    model_name = str(model_cfg.get("name", "Qwen/Qwen2-7B-Instruct"))
    trust_remote_code = bool(model_cfg.get("trust_remote_code", False))

    tokenizer_dir = repo_dir / "tokenizer"
    if tokenizer_dir.exists() and any(tokenizer_dir.iterdir()):
        tokenizer = AutoTokenizer.from_pretrained(
            str(tokenizer_dir),
            use_fast=True,
            trust_remote_code=trust_remote_code,
        )
    else:
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_fast=True,
            trust_remote_code=trust_remote_code,
        )
    tokenizer.add_special_tokens({"additional_special_tokens": SPECIAL_TOKENS})

    llm_model = Model(
        tokenizer=tokenizer,
        model_name=model_name,
        trust_remote_code=trust_remote_code,
    )
    llm_model.enable_lora_adapter()
    llm_model.to(args.llm_device)
    llm_model.eval()

    state_dict = _load_model_state_dict(repo_dir)
    llm_model.load_state_dict(state_dict, strict=False)

    server = KyutaiBridgeServer(
        llm_model=llm_model,
        tokenizer=tokenizer,
        llm_device=args.llm_device,
        kyutai_stt_ws=args.kyutai_stt_ws,
        kyutai_tts_ws=args.kyutai_tts_ws,
        kyutai_api_key=args.kyutai_api_key,
        kyutai_tts_voice=args.kyutai_tts_voice,
        overlap_window_s=args.overlap_window_s,
        max_new_tokens=args.max_new_tokens,
        stt_pre_silence_s=args.stt_pre_silence_s,
    )

    asyncio.run(server.run(args.port))


if __name__ == "__main__":
    main()

