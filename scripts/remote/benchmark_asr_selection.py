"""Measure real-time streaming output on a frozen, independently transcribed set."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import threading
import time
import traceback
from pathlib import Path

import numpy as np
PUNCTUATION = re.compile(r"[.,!?;:]")


def quantiles(values):
    """Keep missing measurements missing."""
    return {"count": len(values), "p50": float(np.percentile(values, 50)) if values else None,
            "p95": float(np.percentile(values, 95)) if values else None}


def align_words(reference, hypothesis):
    """Return an edit alignment, retaining insertions and deletions."""
    costs = [[0] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]
    matches = [[0] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]
    operations = {}
    for i in range(len(reference) + 1):
        costs[i][0] = i
    for j in range(len(hypothesis) + 1):
        costs[0][j] = j
    for i, word in enumerate(reference, 1):
        for j, other in enumerate(hypothesis, 1):
            candidates = [(costs[i - 1][j - 1] + (word != other),
                           -(matches[i - 1][j - 1] + (word == other)), "diagonal"),
                          (costs[i - 1][j] + 1, -matches[i - 1][j], "delete"),
                          (costs[i][j - 1] + 1, -matches[i][j - 1], "insert")]
            distance, negative_matches, operation = min(candidates)
            costs[i][j], matches[i][j] = distance, -negative_matches
            operations[i, j] = operation
    pairs = []
    i, j = len(reference), len(hypothesis)
    while i or j:
        if i and j and operations[i, j] == "diagonal":
            pairs.append((i - 1, j - 1, "equal" if reference[i - 1] == hypothesis[j - 1] else "substitute"))
            i, j = i - 1, j - 1
        elif i and (not j or operations[i, j] == "delete"):
            pairs.append((i - 1, None, "delete"))
            i -= 1
        else:
            pairs.append((None, j - 1, "insert"))
            j -= 1
    return list(reversed(pairs))


class RealtimeAudio:
    """Release 80 ms packets on an independent clock, including explicit EOF drain."""

    def __init__(self, audio, sample_rate, drain_seconds=2.0):
        self.sample_rate = sample_rate
        self.original_length = len(audio)
        self.duration = len(audio) / sample_rate
        self.audio = np.pad(audio, (0, round(drain_seconds * sample_rate)))
        self.available = 0
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.packets = []
        self.started = None
        self.thread = None
        self.consumed = 0

    def start(self):
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._produce, daemon=True)
        self.thread.start()

    def _produce(self):
        packet = round(self.sample_rate * 0.08)
        for end in range(packet, len(self.audio) + packet, packet):
            end = min(end, len(self.audio))
            scheduled = end / self.sample_rate
            if self.stop.wait(max(0, self.started + scheduled - time.monotonic())):
                return
            with self.condition:
                self.available = end
                self.packets.append({"audio_seconds": min(end, self.original_length) / self.sample_rate,
                                     "released_seconds": time.monotonic() - self.started,
                                     "scheduled_seconds": scheduled,
                                     "eof": end >= self.original_length})
                self.condition.notify_all()

    def read(self, start, end):
        end = min(end, len(self.audio))
        with self.condition:
            while self.available < end:
                self.condition.wait(timeout=0.1)
                if self.stop.is_set():
                    raise RuntimeError("Audio input cancelled")
            self.consumed = end
            return self.audio[start:end].copy()

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=2)


class EventSink:
    """Record the unmodified transcript and check prefix monotonicity."""

    def __init__(self, path, source, buffered=False):
        self.path = path
        self.source = source
        self.events = []
        self.text = ""
        self.tokens = []
        self.stream = path.open("w")
        self.buffered = buffered
        self.persistence_seconds = []

    def emit(self, text, token=None):
        now = time.monotonic()
        if token is not None:
            self.tokens.append(token)
        if text == self.text:
            return
        elapsed = now - self.source.started
        event = {"arrival_seconds": elapsed, "wall_time_unix": time.time(), "text": text, "token": token,
                 "rewritten": not text.startswith(self.text),
                 "received_audio_seconds": min(self.source.available, self.source.original_length) / self.source.sample_rate,
                 "consumed_audio_seconds": min(self.source.consumed, self.source.original_length) / self.source.sample_rate,
                 "eof": elapsed >= self.source.duration}
        self.events.append(event)
        self.text = text
        if not self.buffered:
            persistence_started = time.monotonic()
            self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.stream.flush()
            self.persistence_seconds.append(time.monotonic() - persistence_started)

    def close(self):
        if self.buffered:
            self.stream.writelines(json.dumps(event, ensure_ascii=False) + "\n" for event in self.events)
        self.stream.close()
        self.path.with_suffix(".input.json").write_text(json.dumps(self.source.packets))
        self.path.with_suffix(".tokens.json").write_text(json.dumps(self.tokens))


class NemotronBackend:
    """Use the official cache-aware feature generator with uninterrupted RNNT state."""

    sample_rate = 16000

    def __init__(self, model_path, chunk_ms):
        from transformers import AutoModelForRNNT, AutoProcessor
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.lookahead = {160: 1, 320: 3, 560: 6}[chunk_ms]
        self.processor.set_num_lookahead_tokens(self.lookahead)
        self.multilingual = "nemotron3_5" in self.processor.__class__.__name__.lower() or "multi" in str(model_path)
        self.model = AutoModelForRNNT.from_pretrained(model_path, local_files_only=True,
                                                     dtype=torch.float32).to("cuda").eval()

    def run(self, source, sink):
        processor = self.processor
        model = self.model
        first_frames = processor.num_mel_frames_first_audio_chunk
        frames_per_chunk = processor.num_mel_frames_per_audio_chunk
        hop = processor.feature_extractor.hop_length
        n_fft = processor.feature_extractor.n_fft
        extra_inputs = {}

        def features():
            first_size = processor.num_samples_first_audio_chunk
            waveform = source.read(0, first_size)
            waveform = np.pad(waveform, (0, max(0, first_size - len(waveform))))
            inputs = processor(waveform, sampling_rate=16000, is_streaming=True,
                               is_first_audio_chunk=True, return_tensors="pt",
                               **({"language": "en-US"} if self.multilingual else {}))
            extra_inputs.update({k: v.to("cuda") if torch.is_tensor(v) else v
                                 for k, v in inputs.items()
                                 if k not in ("input_features", "attention_mask", "num_lookahead_tokens")})
            yield inputs.input_features[:, :first_frames].to("cuda", dtype=model.dtype)
            frame_index = first_frames
            while True:
                start = frame_index * hop - n_fft // 2
                if start >= len(source.audio):
                    break
                size = processor.num_samples_per_audio_chunk
                waveform = source.read(start, start + size)
                waveform = np.pad(waveform, (0, max(0, size - len(waveform))))
                inputs = processor(waveform, sampling_rate=16000, is_streaming=True,
                                   is_first_audio_chunk=False, return_tensors="pt",
                                   **({"language": "en-US"} if self.multilingual else {}))
                yield inputs.input_features[:, :frames_per_chunk].to("cuda", dtype=model.dtype)
                frame_index += frames_per_chunk

        class TokenRecorder:
            def __init__(self):
                self.ids = []

            def put(self, value):
                ids = value.detach().cpu().reshape(-1).tolist()
                self.ids.extend(ids)
                text = processor.decode(self.ids, skip_special_tokens=True,
                                        clean_up_tokenization_spaces=False)
                sink.emit(text, ids)

            def end(self):
                pass

        with torch.inference_mode():
            # Prime only the first, already-arrived chunk so language conditioning is available.
            generator = features()
            first = next(generator)

            def all_features():
                yield first
                yield from generator

            self.model.generate(input_features=all_features(), num_lookahead_tokens=self.lookahead,
                                streamer=TokenRecorder(), do_sample=False,
                                return_dict_in_generate=True, **extra_inputs)


class KyutaiBackend:
    """Drive Mimi and LMGen one live audio frame at a time."""

    sample_rate = 16000

    def __init__(self, model_path, root):
        from moshi.models import LMGen, loaders
        model_path = Path(model_path)
        config = json.loads((model_path / "config.json").read_text())
        mimi_name = config.get("mimi_name", "")
        weights = [p for p in model_path.glob("*.safetensors") if p.name != mimi_name]
        mimi_weights = ([model_path / mimi_name] if mimi_name and (model_path / mimi_name).exists()
                        else list((root / "models/mimi").glob("*.safetensors")))
        tokenizer_files = list(model_path.glob("*.model"))
        if len(weights) != 1 or len(mimi_weights) != 1 or len(tokenizer_files) != 1:
            raise ValueError("Expected exactly one model, Mimi and tokenizer artifact")
        self.info = loaders.CheckpointInfo.from_hf_repo(
            "kyutai/stt-1b-en_fr", moshi_weights=str(weights[0]),
            mimi_weights=str(mimi_weights[0]), tokenizer=str(tokenizer_files[0]),
            config_path=str(model_path / "config.json"))
        self.mimi = self.info.get_mimi(device="cuda")
        self.tokenizer = self.info.get_text_tokenizer()
        self.lm = self.info.get_moshi(device="cuda", dtype=torch.bfloat16)
        self.generator = LMGen(self.lm, temp=0, temp_text=0.0, use_sampling=False)
        self.prefix_frames = math.ceil(self.info.stt_config.get("audio_silence_prefix_seconds", 1.0) * self.mimi.frame_rate)
        self.config = config

    def run(self, source, sink):
        import soxr
        resampler = soxr.ResampleStream(16000, 24000, 1, dtype="float32", quality="HQ")
        silence = torch.zeros((1, 1, self.mimi.frame_size), device="cuda")
        pending = np.empty(0, dtype=np.float32)
        with torch.inference_mode(), self.mimi.streaming(1), self.generator.streaming(1):
            # Prefix initialization precedes the real audio clock.
            for _ in range(self.prefix_frames):
                self.generator.step(self.mimi.encode(silence))
            torch.cuda.synchronize()
            source.start()
            for start in range(0, len(source.audio), 1280):
                raw = source.read(start, start + 1280)
                converted = resampler.resample_chunk(raw, last=start + 1280 >= len(source.audio))
                pending = np.concatenate((pending, converted))
                while len(pending) >= self.mimi.frame_size:
                    frame = pending[:self.mimi.frame_size]
                    pending = pending[self.mimi.frame_size:]
                    tensor = torch.from_numpy(frame.copy()).reshape(1, 1, -1).to("cuda")
                    tokens = self.generator.step(self.mimi.encode(tensor))
                    if tokens is not None:
                        token = int(tokens[0, 0, 0].item())
                        if token > 3:
                            text = self.tokenizer.id_to_piece(token).replace("▁", " ")
                            sink.emit(sink.text + text, token)


def punctuated_words(text):
    """Map surface word boundaries to following punctuation, without restoring marks."""
    words, marks = [], {}
    for match in re.finditer(r"[\w]+(?:['’][\w]+)*|[.,!?;:]", text):
        token = match.group()
        if PUNCTUATION.fullmatch(token):
            if words:
                marks.setdefault(len(words) - 1, []).append(token)
        else:
            words.append(token.lower().replace("’", "'"))
    return words, marks


def score_sample(row, sink, error=None, acoustic_alignment=None):
    reference = NORMALIZE(row["reference"]).split()
    hypothesis = NORMALIZE(sink.text).split()
    aligned = align_words(reference, hypothesis)
    counts = {kind: sum(p[2] == kind for p in aligned)
              for kind in ("equal", "substitute", "delete", "insert")}
    if not reference:
        counts = {kind: 0 for kind in counts}
    ref_words, ref_marks = punctuated_words(row["reference"])
    hyp_words, hyp_marks = punctuated_words(sink.text)
    surface_alignment = align_words(ref_words, hyp_words)
    matches = {j: i for i, j, kind in surface_alignment if kind == "equal"}
    expected = {(index, mark) for index, marks in ref_marks.items() for mark in marks}
    predicted = {(matches.get(index, f"unmatched-{index}"), mark)
                 for index, marks in hyp_marks.items() for mark in marks}
    if not reference:
        expected, predicted = set(), set()
    online = [e for e in sink.events if not e["eof"]]
    first = next((e for e in sink.events if e["text"].strip()), None)
    word_latencies = []
    alignment_usable = (acoustic_alignment and not acoustic_alignment.get("error")
                        and acoustic_alignment.get("mean_label_log_probability", -math.inf) >= -3.0
                        and [w["word"] for w in acoustic_alignment["words"]] == reference)
    if alignment_usable:
        event_words = [(e["arrival_seconds"], NORMALIZE(e["text"]).split()) for e in sink.events]
        for i, j, kind in aligned:
            if kind != "equal":
                continue
            arrival = next((at for at, words in event_words
                            if len(words) > j and words[:j + 1] == hypothesis[:j + 1]), None)
            if arrival is not None:
                word_latencies.append(arrival - acoustic_alignment["words"][i]["end"])
    return {"sample_id": row["sample_id"], "duration_seconds": row["duration_seconds"],
            "reference": row["reference"], "text": sink.text,
            "online_text": online[-1]["text"] if online else "", "error": error,
            "reference_words": len(reference), **counts,
            "wer": (counts["substitute"] + counts["delete"] + counts["insert"]) / len(reference) if reference else None,
            "rewrites": sum(e["rewritten"] for e in sink.events),
            "first_text_seconds": first["arrival_seconds"] if first else None,
            "last_text_relative_to_eof_seconds": sink.events[-1]["arrival_seconds"] - row["duration_seconds"] if sink.events else None,
            "online_punctuation": bool(PUNCTUATION.search(online[-1]["text"])) if online else False,
            "punctuation_tp": len(expected & predicted), "punctuation_fp": len(predicted - expected),
            "punctuation_fn": len(expected - predicted),
            "estimated_word_latency_seconds": word_latencies,
            "alignment_usable": bool(alignment_usable),
            "alignment_error": acoustic_alignment.get("error") if acoustic_alignment else "not available",
            "sentence_punctuation_latency_seconds": None,
            "event_persistence_max_seconds": max(getattr(sink, "persistence_seconds", []), default=0),
            "event_persistence_total_seconds": sum(getattr(sink, "persistence_seconds", [])),
            "max_input_scheduling_delay_seconds": max((p["released_seconds"] - p["scheduled_seconds"] for p in sink.source.packets), default=None)}


def summarize(rows):
    errors = sum(r["substitute"] + r["delete"] + r["insert"] for r in rows)
    words = sum(r["reference_words"] for r in rows)
    tp, fp, fn = (sum(r["punctuation_" + field] for r in rows) for field in ("tp", "fp", "fn"))
    def ends_with_sentence_mark(text):
        return bool(re.search(r'''[.!?]["'”’)]*\s*$''', text))
    return {"samples": len(rows), "failures": sum(r["error"] is not None for r in rows),
            "reference_words": words, "word_errors": errors, "wer": errors / words if words else None,
            "rewrites": sum(r["rewrites"] for r in rows),
            "online_punctuation_samples": sum(r["online_punctuation"] for r in rows),
            "online_terminal_punctuation_samples": sum(ends_with_sentence_mark(r["online_text"]) for r in rows),
            "final_terminal_punctuation_samples": sum(ends_with_sentence_mark(r["text"]) for r in rows),
            "eof_only_terminal_punctuation_samples": sum(ends_with_sentence_mark(r["text"]) and not ends_with_sentence_mark(r["online_text"]) for r in rows),
            "punctuation_tp": tp, "punctuation_fp": fp, "punctuation_fn": fn,
            "punctuation_precision": tp / (tp + fp) if tp + fp else None,
            "punctuation_recall": tp / (tp + fn) if tp + fn else None,
            "punctuation_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "first_text_seconds": quantiles([r["first_text_seconds"] for r in rows if r["first_text_seconds"] is not None]),
            "estimated_word_latency_seconds": quantiles([v for r in rows for v in r["estimated_word_latency_seconds"]]),
            "aligned_reference_words": sum(r["reference_words"] for r in rows if r["alignment_usable"]),
            "correct_words": sum(r["equal"] for r in rows),
            "last_text_relative_to_eof_seconds": quantiles([r["last_text_relative_to_eof_seconds"] for r in rows if r["last_text_relative_to_eof_seconds"] is not None])}


def main():
    global torch, NORMALIZE
    import soundfile as sf
    import torch
    from whisper_normalizer.english import EnglishTextNormalizer

    NORMALIZE = EnglishTextNormalizer()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--candidate", choices=["nemotron_en", "nemotron_multi", "kyutai"], required=True)
    parser.add_argument("--chunk-ms", type=int, default=160)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--drain-seconds", type=float, default=2.0)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--buffer-events", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(0)
    manifest_path = args.manifest or args.root / "dataset/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    alignment_path = args.root / "dataset/alignments.json"
    alignments = json.loads(alignment_path.read_text())["samples"] if alignment_path.exists() else {}
    model_path = args.root / "models" / args.candidate
    started = time.monotonic()
    backend = KyutaiBackend(model_path, args.root) if args.candidate == "kyutai" else NemotronBackend(model_path, args.chunk_ms)
    load_seconds = time.monotonic() - started
    selected = [r for r in manifest["samples"] if r["split"] == "test"][:args.limit]
    warmup = next(r for r in manifest["samples"] if r["split"] == "dev")
    rows = []
    for index, row in enumerate([warmup, warmup] + selected):
        is_warmup = index < 2
        sample_index = index - 1
        audio_path = Path(row["path"])
        if hashlib.sha256(audio_path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Audio hash mismatch: {audio_path}")
        audio, rate = sf.read(audio_path, dtype="float32")
        if rate != 16000 or audio.ndim != 1:
            raise ValueError("Expected mono 16 kHz FLEURS input")
        source = RealtimeAudio(audio, rate, drain_seconds=args.drain_seconds)
        sink = EventSink(args.output / (f"warmup-{index}.jsonl" if is_warmup else f"sample-{sample_index:04d}.jsonl"), source,
                         buffered=args.buffer_events)
        error = None
        try:
            if args.candidate != "kyutai":
                source.start()
            backend.run(source, sink)
            torch.cuda.synchronize()
        except Exception:
            error = traceback.format_exc()
            print(error, flush=True)
        finally:
            source.close()
            sink.close()
        result = score_sample(row, sink, error, alignments.get(row["sample_id"]))
        if is_warmup:
            (args.output / f"warmup-{index}.json").write_text(json.dumps(result, indent=2))
            if error or not sink.text.strip():
                raise RuntimeError("Cold initialization must complete with nonempty output")
            if index == 1 and not any(e["text"].strip() and not e["eof"] for e in sink.events):
                raise RuntimeError("Warmup must complete with nonempty online output")
            torch.cuda.reset_peak_memory_stats()
        else:
            rows.append(result)
            with (args.output / "samples.jsonl").open("a") as out:
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(json.dumps({"index": sample_index, "candidate": args.candidate, "wer": result["wer"],
                              "text": result["text"], "error": bool(error)}), flush=True)
    report = {"candidate": args.candidate, "chunk_ms": args.chunk_ms if args.candidate != "kyutai" else None,
              "dataset_revision": manifest["revision"], "model_load_seconds": load_seconds,
              "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
              "peak_reserved_bytes": torch.cuda.max_memory_reserved(), "drain_seconds": args.drain_seconds,
              "normalizer": "whisper-normalizer==0.1.12 EnglishTextNormalizer",
              "event_persistence": "after decode" if args.buffer_events else "synchronous per event",
              "summary": summarize(rows), "samples": rows}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
