"""Compact a Stage A4 acceptance report before it is committed.

``run_xtalk_duplex_a4_node_job.sh`` copies the key evidence of a run into the
tracked ``reports/duplex_acceptance/<tag>/`` tree.  Raw as-captured evidence
(per-tick ``events``, ``timeline.played_text`` snapshots, ``raw_outputs`` /
``protocol_tokens`` streams and the sampler CSVs) is bulky: a single run added
over ten thousand lines to ``git diff`` while carrying little verdict value.

This script rewrites those files **in place** in the report directory:

* per-tick arrays are replaced by their counts - ``events`` becomes
  ``{event_type: count}``, ``timeline.played_text`` becomes one entry per
  response with the snapshot count and the last played text, and
  ``raw_outputs`` / ``protocol_tokens`` become token histograms, which is what
  the task order actually reasons about ("how many ``talking`` vs
  ``interruption`` tokens");
* strings longer than ``MAX_STRING`` characters (model replies, ASR finals) are
  truncated with an explicit marker and the dropped length;
* ``*_samples.csv`` sampler dumps become ``<name>_summary.json`` with the row
  count and per-column min / median / max.

Everything else - statuses, error lists, ids, timings, byte counters, logs and
``steps.jsonl`` - is preserved, so the committed report still answers "did this
run pass, and what were the numbers".  The full arrays are not lost: they stay
in ``data/runs/<tag>/`` next to the audio, which is git-ignored by policy.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

#: Strings longer than this are truncated (model replies / ASR transcripts).
MAX_STRING = 600

#: Per-tick stream keys, replaced by counts.  ``events`` is a list of dicts;
#: the others are lists of tokens or text snapshots.
_EVENT_KEY = "events"
_PLAYED_TEXT_KEY = "played_text"
_STREAM_KEYS = ("raw_outputs", "protocol_tokens")


def _truncate(text: str) -> str:
    """Return ``text`` unchanged when short, else a marked head plus its length."""
    if len(text) <= MAX_STRING:
        return text
    return f'{text[:MAX_STRING]}…[truncated {len(text) - MAX_STRING} chars]'


def _event_counts(events: list) -> dict:
    """Summarize a per-tick event list as ``{name: count}`` plus its total."""
    names = Counter()
    seconds = []
    for event in events:
        if isinstance(event, dict):
            name = (event.get("action") or event.get("event") or event.get("type")
                    or event.get("kind") or "unknown")
            if isinstance(event.get("seconds"), (int, float)):
                seconds.append(float(event["seconds"]))
        else:
            name = str(event)
        names[str(name)] += 1
    summary = {"ticks": len(events), "by_event": dict(sorted(names.items()))}
    if seconds:
        summary["span_seconds"] = round(max(seconds) - min(seconds), 3)
    return summary


def _token_counts(tokens: list) -> dict:
    """Summarize a raw-output / protocol-token stream as a token histogram."""
    counts = Counter(str(token) for token in tokens)
    return {"count": len(tokens), "tokens": dict(sorted(counts.items()))}


def _played_text_summary(played: dict) -> dict:
    """Summarize per-response played-text snapshots: how many, and the last one."""
    summary = {}
    for response_id, snapshots in played.items():
        if isinstance(snapshots, list):
            summary[str(response_id)] = {
                "snapshots": len(snapshots),
                "last": _truncate(str(snapshots[-1])) if snapshots else None,
            }
        else:
            summary[str(response_id)] = _truncate(str(snapshots))
    return summary


def compact(node: Any, key: str | None = None) -> Any:
    """Recursively compact a JSON value according to the module policy."""
    if isinstance(node, dict):
        result = {}
        for name, value in node.items():
            if name == _EVENT_KEY and isinstance(value, list):
                result[name] = _event_counts(value)
            elif name == _PLAYED_TEXT_KEY and isinstance(value, dict):
                result[name] = _played_text_summary(value)
            elif name in _STREAM_KEYS and isinstance(value, list):
                result[name] = _token_counts(value)
            else:
                result[name] = compact(value, name)
        return result
    if isinstance(node, list):
        return [compact(item, key) for item in node]
    if isinstance(node, str):
        return _truncate(node)
    return node


def summarize_csv(path: Path) -> dict:
    """Return row count plus per-column min / median / max for a sampler CSV."""
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle))
    columns: dict[str, dict] = {}
    for column in (rows[0].keys() if rows else []):
        values = []
        for row in rows:
            try:
                values.append(float(row[column]))
            except (TypeError, ValueError):
                continue
        if values:
            columns[column] = {
                "min": min(values),
                "median": statistics.median(values),
                "max": max(values),
            }
    return {"source": path.name, "rows": len(rows), "columns": columns}


def line_count(path: Path) -> int:
    """Return the file's line count, or 0 when unreadable."""
    try:
        return len(path.read_text(errors="replace").splitlines())
    except Exception:
        return 0


def main() -> int:
    """Compact one report directory in place and print the size delta."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True,
                        help="reports/duplex_acceptance/<tag> to rewrite in place")
    parser.add_argument("--dry-run", action="store_true", help="report sizes without writing")
    args = parser.parse_args()

    before = after = 0
    changed = []
    for path in sorted(args.report_dir.rglob("*.json")):
        original = line_count(path)
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        compacted = compact(payload)
        text = json.dumps(compacted, ensure_ascii=False, indent=1) + "\n"
        new_lines = len(text.splitlines())
        before += original
        after += new_lines
        if new_lines != original:
            changed.append((path.relative_to(args.report_dir).as_posix(), original, new_lines))
            if not args.dry_run:
                path.write_text(text, encoding="utf-8")

    for path in sorted(args.report_dir.rglob("*_samples.csv")):
        original = line_count(path)
        summary_path = path.with_name(path.stem + "_summary.json")
        before += original
        text = json.dumps(summarize_csv(path), ensure_ascii=False, indent=1) + "\n"
        new_lines = len(text.splitlines())
        after += new_lines
        changed.append((summary_path.relative_to(args.report_dir).as_posix(), original, new_lines))
        if not args.dry_run:
            path.unlink()
            summary_path.write_text(text, encoding="utf-8")

    for name, old, new in changed:
        print(f"[compact] {name}: {old} -> {new} lines")
    print(f"[compact] total {before} -> {after} lines in {args.report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
