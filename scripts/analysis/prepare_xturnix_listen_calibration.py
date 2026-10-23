"""Freeze grouped English text observations for Listen-only calibration."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import urllib.request

REVISION = "ca9d98a9686b920a2d8c9eb984224ba9be74e4dd"
EXCLUDED_GROUPS = {"en__875_82", "en__977_89"}
SPLIT_SEED = "xtx010-listen-v1:"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_rows(output: Path) -> tuple[list[dict], list[dict]]:
    rows, ledger = [], []
    total_bytes = 0
    for offset in range(0, 400, 100):
        url = ("https://datasets-server.huggingface.co/rows?"
               "dataset=livekit%2Feot-bench-data&config=en&split=validation"
               f"&offset={offset}&length=100")
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        total_bytes += len(data)
        if len(data) > 8 * 1024 * 1024 or total_bytes > 32 * 1024 * 1024:
            raise ValueError("metadata read budget exceeded")
        result = json.loads(data)
        if result["num_rows_total"] != 400 or result["partial"]:
            raise ValueError("source population changed or is partial")
        page = result["rows"]
        if len(page) != 100:
            raise ValueError("incomplete source page")
        for entry in page:
            if entry["truncated_cells"]:
                raise ValueError("truncated source metadata")
            row = dict(entry["row"])
            audio = row.pop("audio")
            if not audio or any(f"/{REVISION}/" not in item["src"] for item in audio):
                raise ValueError("source revision mismatch")
            if row["language"] != "en":
                raise ValueError("non-English source row")
            rows.append(row)
        ledger.append({"url": url, "bytes": len(data), "sha256": sha(data)})
        print(f"metadata_rows={len(rows)}", flush=True)
    if len({row["id"] for row in rows}) != 400:
        raise ValueError("duplicate source identifiers")
    (output / "source_metadata.json").write_text(json.dumps(rows, ensure_ascii=False) + "\n")
    return rows, ledger


def history_messages(messages: list[dict]) -> tuple[list[dict], int]:
    result, changes = [], 0
    for message in messages:
        role, content = message["role"], message["content"]
        if role not in {"user", "assistant"}:
            raise ValueError("unsupported source history role")
        if not content or not content.strip():
            changes += 1
            continue
        if result and result[-1]["role"] == role:
            result[-1]["content"] += "\n" + content
            changes += 1
        else:
            result.append({"role": role, "content": content})
    if result and result[0]["role"] == "assistant":
        result.pop(0)
        changes += 1
    return result, changes


def make_events(row: dict) -> tuple[list[dict], list[dict]]:
    match = re.fullmatch(r"(.+)__user_turn_\d+", row["id"])
    if match is None:
        raise ValueError("source ID does not provide a conversation group")
    group = match[1]
    if group in EXCLUDED_GROUPS:
        return [], [{"turn_id": row["id"], "reason": "previous_source_format_inspection"}]
    split = "dev" if int(sha((SPLIT_SEED + group).encode()), 16) % 2 == 0 else "test"
    history, changes = history_messages(row["messages"])
    if history and history[-1]["role"] != "assistant":
        return [], [{"turn_id": row["id"], "reason": "history_does_not_end_in_assistant"}]
    words, spans = row["words"], row["silence_spans"]
    if not words or not spans:
        return [], [{"turn_id": row["id"], "reason": "missing_words_or_silences"}]
    for word in words:
        if (not all(math.isfinite(word[k]) for k in ("start", "end"))
                or word["start"] < 0 or word["end"] < word["start"]):
            raise ValueError("invalid source word timing")
    events, exclusions = [], []
    for index, span in enumerate(spans):
        observed = span["start"] + 0.1
        if span["end"] + 1e-7 < observed:
            exclusions.append({"turn_id": row["id"], "span_index": index,
                               "reason": "silence_shorter_than_100ms"})
            continue
        current = " ".join(w["word"].strip() for w in words if w["end"] <= observed + 1e-7).strip()
        messages = [dict(message) for message in history] + [{"role": "user", "content": current}]
        event = {
            "sample_id": f"{row['id']}:span_{index:03d}", "turn_id": row["id"],
            "conversation_id": group, "split": split, "state": "listening",
            "target": "start" if index == len(spans) - 1 else "keep",
            "observed_until": observed, "messages": messages,
            "history_changes": changes, "preparation_error": None if current else "empty_current_prefix",
        }
        event["messages_sha256"] = sha(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode())
        events.append(event)
    return events, exclusions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.source_cache:
        cached_summary = json.loads((args.source_cache / "prepare_summary.json").read_text())
        cached = (args.source_cache / "source_metadata.json").read_bytes()
        if (sha(cached) != cached_summary["source_metadata_sha256"]
                or cached_summary["source_revision"] != REVISION):
            raise ValueError("source cache verification failed")
        rows = json.loads(cached)
        requests = cached_summary["requests"]
        (args.output / "source_metadata.json").write_bytes(cached)
    else:
        rows, requests = fetch_rows(args.output)
    events, exclusions = [], []
    for row in rows:
        selected, rejected = make_events(row)
        events.extend(selected)
        exclusions.extend(rejected)
    groups = {split: {e["conversation_id"] for e in events if e["split"] == split}
              for split in ("dev", "test")}
    if groups["dev"] & groups["test"]:
        raise ValueError("conversation group leakage")
    inputs = {}
    for split in ("dev", "test"):
        selected = [e for e in events if e["split"] == split]
        if not selected or not any(e["target"] == "keep" for e in selected):
            raise ValueError("split lacks positive or negative observations")
        encoded = json.dumps(selected, ensure_ascii=False).encode()
        path = args.output / f"{split}.json.gz"
        path.write_bytes(gzip.compress(encoded, mtime=0))
        inputs[split] = {"sha256": sha(path.read_bytes()), "events": len(selected),
                         "turns": len({e["turn_id"] for e in selected}),
                         "conversations": len(groups[split]),
                         "labels": dict(Counter(e["target"] for e in selected))}
    manifest = [{k: v for k, v in e.items() if k != "messages"} for e in events]
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    summary = {"schema": "xtx010-listen-data-v1", "source_revision": REVISION,
               "history_normalization": "drop_empty_merge_adjacent_drop_initial_assistant",
               "reused_source_cache": str(args.source_cache) if args.source_cache else None,
               "source_rows": len(rows), "split_seed": SPLIT_SEED,
               "inputs": inputs, "exclusions": exclusions,
               "source_metadata_sha256": sha((args.output / "source_metadata.json").read_bytes()),
               "requests": requests}
    (args.output / "prepare_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(inputs), flush=True)


if __name__ == "__main__":
    main()
