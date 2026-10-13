"""Replay recorded ASR micro-turns through the official model to isolate marker decisions.

The probe answers one question: given the *same* ASR text stream that a recorded A4 run
produced, does the interleave marker the DuplexCascade weights emit depend on the text
shape we hand them (sentence punctuation, casing, fragment size)?

It is a text-only closed loop. It never touches audio, ASR or TTS: it reads the
``update_asr`` events stored in an ``a4_report.json``, replays them on the runtime's
0.6 s micro-turn clock, and calls the official model service exactly the way
``DuplexRuntimeAdapter`` does. Each variant changes only the text that reaches the model,
so any marker change is attributable to that change alone.
"""

from __future__ import annotations

import argparse
import json
import re
import string
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

MARKERS = (
    "<|no voice|>", "<|user is talking|>", "<|user finish talking|>",
    "<|user is thinking|>", "<|user interruption|>", "<|user backchannel|>",
)
MARKER_PATTERN = re.compile("|".join(re.escape(marker) for marker in MARKERS))

# Sentence punctuation only. Apostrophes and hyphens stay so contractions such as
# "don't" are not split into two words the model was never trained to see apart.
SENTENCE_PUNCTUATION = set(string.punctuation) - {"'", "-", "_"} | set("“”‘’…—、，。？！；：（）《》【】")


def normalize(text: str, variant: str) -> str:
    """Return the user text one variant sends to the model.

    Parameters
    ----------
    text : str
        Raw user micro-turn text as recorded from the ASR stream.
    variant : str
        ``raw`` keeps the text untouched; ``strip`` removes sentence punctuation;
        ``strip_lower`` additionally lowercases. ``burst`` is applied when the text is
        emitted, not here.

    Returns
    -------
    str
        Normalized text; an empty result becomes ``<|no voice|>`` in the prompt.
    """
    if variant not in ("strip", "strip_lower"):
        return text
    cleaned = "".join(" " if character in SENTENCE_PUNCTUATION else character for character in text)
    cleaned = " ".join(cleaned.split())
    return cleaned.lower() if variant == "strip_lower" else cleaned


class MarkerReplay:
    """Replay one recorded session's ASR stream through the model service.

    Parameters
    ----------
    model_url : str
        Official model service root, e.g. ``http://127.0.0.1:8006``.
    variant : str
        Text variant applied at the wire boundary (see :func:`normalize`).
    interval : float
        Micro-turn clock, matching ``duplex_micro_turn_seconds``.
    max_new_tokens : int
        Per-tick generation budget, matching the runtime default.
    timeout : float
        HTTP deadline per micro-turn.
    """

    def __init__(self, model_url: str, variant: str, interval: float = 0.6,
                 max_new_tokens: int = 64, timeout: float = 30.0, dry_run: bool = False,
                 clock: str = "grid") -> None:
        self.model_url = model_url.rstrip("/")
        self.variant = variant
        self.interval = interval
        self.max_new_tokens = max_new_tokens
        self.timeout = timeout
        self.dry_run = dry_run
        self.clock = clock
        self.history: list[dict[str, Any]] = []
        self.prefix = ""
        self.sent_prefix = ""
        self.pending = ""
        self.ticks: list[dict[str, Any]] = []

    def accept(self, text: str) -> None:
        """Update the visible ASR prefix the way ``MicroTurnAssembler`` does."""
        self.prefix = text

    def flush(self) -> tuple[str, str]:
        """Append one user micro-turn and return ``(raw delta, emitted wire text)``."""
        previous = self.sent_prefix
        rewritten = not self.prefix.startswith(previous)
        delta = self.prefix if rewritten else self.prefix[len(previous):]
        self.sent_prefix = self.prefix
        if rewritten:
            # ``_append_user`` repairs earlier turns and only the leftover text becomes
            # this tick's delta; appending the whole prefix again would duplicate it.
            delta = self._repair_rewrite()
        if self.variant == "burst":
            # Hold one-word fragments until a short burst has accumulated.
            self.pending += delta
            emitted = self.pending if len(self.pending.split()) >= 3 else ""
            self.pending = "" if emitted else self.pending
        else:
            emitted = normalize(delta, self.variant)
        self.history.append({"role": "user", "text": emitted, "source_text": emitted})
        return delta, emitted

    def _repair_rewrite(self) -> str:
        """Rewrite already emitted user micro-turns and return the leftover text."""
        entries = [item for item in self.history if item["role"] == "user" and item["source_text"]]
        remaining = self.prefix
        for index, item in enumerate(entries):
            count = len(item["source_text"]) if index < len(entries) - 1 else len(remaining)
            replacement, remaining = remaining[:count], remaining[count:]
            item["source_text"] = replacement
            item["text"] = replacement
        return remaining

    def wire_history(self) -> list[dict[str, Any]]:
        """Return the request history in the exact shape ``DuplexModelClient`` sends."""
        wire: list[dict[str, Any]] = []
        for item in self.history:
            if item["role"] == "user":
                wire.append({"role": "user", "text": item["text"]})
            else:
                wire.append({"role": "assistant", "token_ids": list(item["token_ids"])})
        return wire

    def tick(self) -> dict[str, Any]:
        """Run one micro-turn and record its markers, text and token ids."""
        delta, emitted = self.flush()
        if self.dry_run:
            # Offline mode: validate the replayed clock and deltas without a model.
            record = {"tick": len(self.ticks), "delta": delta, "wire_text": emitted,
                      "markers": [], "text": "", "prompt_tokens": 0, "token_ids": [],
                      "seconds": 0.0}
            self.ticks.append(record)
            return record
        payload = json.dumps({"history": self.wire_history(), "max_new_tokens": self.max_new_tokens}).encode()
        request = urllib.request.Request(self.model_url + "/generate", data=payload,
                                         headers={"Content-Type": "application/json"})
        pieces: list[str] = []
        token_ids: tuple[int, ...] = ()
        prompt_tokens = 0
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for line in response:
                item = json.loads(line)
                if "error" in item:
                    raise RuntimeError(item["error"])
                if "text" in item:
                    pieces.append(item["text"])
                if "finish_reason" in item:
                    token_ids = tuple(item.get("token_ids") or ())
                    prompt_tokens = int(item.get("prompt_tokens") or 0)
        elapsed = time.monotonic() - started
        if not token_ids:
            raise RuntimeError("model service returned no token ids")
        text = "".join(pieces)
        self.history.append({"role": "assistant", "token_ids": list(token_ids), "text": text})
        record = {"tick": len(self.ticks), "delta": delta, "wire_text": emitted,
                  "markers": MARKER_PATTERN.findall(text), "text": text,
                  "prompt_tokens": prompt_tokens, "token_ids": list(token_ids),
                  "seconds": round(elapsed, 3)}
        self.ticks.append(record)
        return record


def asr_stream(report: dict[str, Any]) -> list[tuple[float, str]]:
    """Extract ``(seconds, text)`` ASR updates from a recorded A4 report."""
    stream = [(float(event["seconds"]), str((event.get("data") or {}).get("text", "")))
              for event in report.get("events", []) if event.get("action") == "update_asr"]
    if not stream:
        raise ValueError("report contains no update_asr events")
    return stream


def truth_stream(sample_dir: Path, report: dict[str, Any], keep_punctuation: bool = False) -> list[tuple[float, str]]:
    """Build the user stream from FDB's own ``interrupt.json`` text.

    The recorded ASR stream carries the recognizer's wording, punctuation and revisions.
    This variant replaces it with the dataset's ground-truth sentences: the context
    question spread over its recorded span, then the interrupting question spread word by
    word over the declared interruption window. It answers "would the model behave
    differently if it received the intended words instead of our ASR output?".

    Parameters
    ----------
    sample_dir : Path
        Directory holding ``interrupt.json``.
    report : dict
        Recorded A4 report, used only for the context question's recorded span.
    keep_punctuation : bool
        Keep the metadata's written punctuation. Default ``False`` so the stream looks
        like a streaming STT word stream, leaving word choice as the only difference from
        the ``strip`` variant.

    Returns
    -------
    list of (seconds, cumulative text)
        A monotonic prefix stream in the same shape as :func:`asr_stream`.
    """
    meta = json.loads((sample_dir / "interrupt.json").read_text())[0]
    context_words = meta["context"].split()
    interrupt_words = meta["interrupt"].split()
    start, end = float(meta["timestamp"][0]), float(meta["timestamp"][1])
    asr = asr_stream(report)
    first = asr[0][0]
    before = [seconds for seconds, _ in asr if seconds <= start]
    last = before[-1] if before else first

    def render(words: list[str]) -> str:
        text = " ".join(words)
        return text if keep_punctuation else normalize(text, "strip")

    events: list[tuple[float, str]] = []
    step = max(0.05, (last - first) / max(1, len(context_words)))
    for index in range(len(context_words)):
        events.append((round(first + step * index, 3), render(context_words[:index + 1])))
    step = max(0.05, (end - start) / max(1, len(interrupt_words)))
    for index in range(len(interrupt_words)):
        events.append((round(start + step * index, 3), render(context_words + interrupt_words[:index + 1])))
    return events


def replay_sample(sample_dir: Path, model_url: str, variant: str, interval: float,
                  max_new_tokens: int, dry_run: bool = False, clock: str = "grid") -> dict[str, Any]:
    """Replay one sample directory and return its marker evidence.

    Parameters
    ----------
    sample_dir : Path
        Directory holding ``a4_report.json`` and optionally ``interrupt.json``.
    model_url, variant, interval, max_new_tokens
        Forwarded to :class:`MarkerReplay`.
    dry_run : bool
        Replay the clock and the deltas without calling the model.
    clock : str
        ``grid`` holds a deterministic 0.6 s grid so every variant sees identical
        deltas; ``absorbed`` lets generation latency delay the next tick, which is what
        the runtime does when inference is slower than the interval.

    Returns
    -------
    dict
        Recorded and reproduced markers, the per-tick log, and the text produced after
        the recorded interruption end.
    """
    report = json.loads((sample_dir / "a4_report.json").read_text())
    interrupt_path = sample_dir / "interrupt.json"
    interrupt_end = None
    if interrupt_path.is_file():
        interrupt_end = float(json.loads(interrupt_path.read_text())[0]["timestamp"][1])
    if variant == "truth":
        stream = truth_stream(sample_dir, report)
    elif variant == "truth_punct":
        stream = truth_stream(sample_dir, report, keep_punctuation=True)
    else:
        stream = asr_stream(report)
    replay = MarkerReplay(model_url, variant, interval, max_new_tokens, dry_run=dry_run, clock=clock)

    index = 0
    next_tick = stream[0][0] + interval
    end_time = float(report.get("send_seconds") or stream[-1][0])
    while next_tick <= end_time:
        while index < len(stream) and stream[index][0] <= next_tick:
            replay.accept(stream[index][1])
            index += 1
        record = replay.tick()
        record["clock"] = round(next_tick, 3)
        next_tick += max(record["seconds"], interval) if clock == "absorbed" else interval

    recorded = report.get("timeline", {}).get("protocol_tokens", [])
    produced = [marker for tick in replay.ticks for marker in tick["markers"]]
    after = [tick for tick in replay.ticks if interrupt_end is not None
             and tick["clock"] >= interrupt_end]
    return {
        "sample": sample_dir.name,
        "variant": variant,
        "recorded_protocol_tokens": recorded,
        "reproduced_protocol_tokens": produced,
        "reproduced_matches_recorded": produced == recorded,
        "interrupt_end": interrupt_end,
        "markers_after_interrupt": [marker for tick in after for marker in tick["markers"]],
        "text_after_interrupt": "".join(tick["text"] for tick in after),
        "ticks": replay.ticks,
    }


def discover_samples(root: Path, wanted: Iterable[str]) -> list[Path]:
    """Return sample directories under ``root`` that carry an A4 report."""
    names = {name for name in wanted if name}
    found = [path for path in sorted(root.iterdir())
             if path.is_dir() and (path / "a4_report.json").is_file()]
    if names:
        found = [path for path in found if path.name in names]
    if not found:
        raise SystemExit(f"no sample directories with a4_report.json under {root}")
    return found


def main() -> None:
    """Run every requested variant over every requested sample and write one JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True,
                        help="Directory holding per-sample subdirectories with a4_report.json")
    parser.add_argument("--samples", default="", help="Comma separated sample names; default all")
    parser.add_argument("--model-url", default="http://127.0.0.1:8006")
    parser.add_argument("--variants", default="raw,strip,strip_lower",
                        help="Comma separated: raw, strip, strip_lower, burst")
    parser.add_argument("--interval", type=float, default=0.6)
    parser.add_argument("--clock", choices=("grid", "absorbed"), default="grid",
                        help="grid keeps a deterministic tick phase across variants")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=1,
                        help="Run each sample/variant this many times to expose decoding instability")
    parser.add_argument("--dry-run", action="store_true",
                        help="Replay the clock and the deltas without calling the model")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    samples = discover_samples(args.sample_root, args.samples.split(","))
    variants = [name for name in args.variants.split(",") if name]
    results = []
    for sample in samples:
        for variant in variants:
            for repeat in range(max(1, args.repeats)):
                started = time.monotonic()
                evidence = replay_sample(sample, args.model_url, variant, args.interval,
                                         args.max_new_tokens, dry_run=args.dry_run, clock=args.clock)
                evidence["variant"] = variant if args.repeats == 1 else f"{variant}#{repeat + 1}"
                evidence["seconds"] = round(time.monotonic() - started, 2)
                results.append(evidence)
                print(json.dumps({"sample": sample.name, "variant": evidence["variant"],
                                  "matches_recorded": evidence["reproduced_matches_recorded"],
                                  "ticks": len(evidence["ticks"]),
                                  "markers": " ".join(evidence["reproduced_protocol_tokens"]) or "(none)"},
                                 ensure_ascii=False), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "model_url": args.model_url, "interval": args.interval, "clock": args.clock,
        "sample_root": str(args.sample_root), "results": results}, ensure_ascii=False, indent=1))
    summary = [{key: evidence[key] for key in (
        "sample", "variant", "recorded_protocol_tokens", "reproduced_protocol_tokens",
        "reproduced_matches_recorded", "interrupt_end", "markers_after_interrupt",
        "text_after_interrupt", "seconds")} for evidence in results]
    for evidence, row in zip(results, summary):
        row["ticks"] = len(evidence["ticks"])
    summary_path = args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({
        "model_url": args.model_url, "interval": args.interval, "clock": args.clock,
        "sample_root": str(args.sample_root), "results": summary}, ensure_ascii=False, indent=1))
    print(json.dumps({"probe": "done", "results": len(results), "out": str(args.out),
                      "summary": str(summary_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
