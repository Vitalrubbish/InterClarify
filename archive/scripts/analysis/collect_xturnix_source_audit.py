"""Collect bounded, causal text packets for the XTX-009 source audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import urllib.request
import zipfile


DAILY_REVISION = "05a0173dac8e68fb2b22190cfc5c22248538a1a6"
SWDA_REVISION = "3baa1fe49ebfa0fdb340eb6f69ee770836901cd9"
SWDA_ZIP_SIZE = 14_449_197
MAX_READ = 1_048_576
MAX_TOTAL = 8 * MAX_READ


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SourceReader:
    """Fetch serial, bounded responses and retain a verification ledger."""

    def __init__(self, output: Path):
        self.output = output
        self.total = 0
        self.ledger: list[dict] = []

    def get(self, url: str, byte_range: tuple[int, int] | None = None) -> bytes:
        headers = {"User-Agent": "ParaThink-source-audit"}
        if byte_range is not None:
            start, end = byte_range
            if start < 0 or end < start or end - start + 1 > MAX_READ:
                raise ValueError("invalid inspection byte range")
            headers["Range"] = f"bytes={start}-{end}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            content_range = response.headers.get("Content-Range")
            if byte_range is not None:
                expected = f"bytes {start}-{end}/{SWDA_ZIP_SIZE}"
                if response.status != 206 or content_range != expected:
                    raise ValueError(f"server did not honor requested range: {content_range}")
            elif response.status != 200:
                raise ValueError("expected a complete source response")
            data = response.read(MAX_READ + 1)
        if len(data) > MAX_READ or self.total + len(data) > MAX_TOTAL:
            raise ValueError("source inspection byte budget exceeded")
        if byte_range is not None and len(data) != end - start + 1:
            raise ValueError("incomplete range response")
        self.total += len(data)
        item = {
            "url": url, "range": byte_range, "content_range": content_range,
            "bytes": len(data), "sha256": digest(data),
        }
        self.ledger.append(item)
        (self.output / f"response_{len(self.ledger):03d}.bin").write_bytes(data)
        return data


def packet(source: str, conversation: str, locator: str, rows: list[dict],
           target: int, selection: str, source_hash: str) -> dict:
    history = rows[:target + 1]
    current_bytes = json.dumps(history, ensure_ascii=False, sort_keys=True).encode()
    return {
        "source": source, "conversation_id": conversation, "locator": locator,
        "source_sha256": source_hash, "selection": selection,
        "observed_through": history[-1]["source_row"],
        "current_history_sha256": digest(current_bytes), "history": history,
        "system_state": None, "target_action": None,
        "reviewer": "codex_single_reviewer", "future_test_exclusion": True,
    }


def read_dailytalk(reader: SourceReader) -> list[dict]:
    url = (f"https://raw.githubusercontent.com/keonlee9420/DailyTalk/{DAILY_REVISION}/"
           "preprocessed_data/DailyTalk/val_phone.txt")
    data = reader.get(url)
    groups: dict[str, list[dict]] = {}
    for line_number, line in enumerate(data.decode().splitlines(), 1):
        parts = line.split("|")
        if len(parts) != 5:
            raise ValueError("unexpected DailyTalk field count")
        name, speaker, _, text, _ = parts
        match = re.fullmatch(r"(\d+)_([01])_d(\d+)", name)
        if match is None or match[2] != speaker:
            raise ValueError("unexpected DailyTalk utterance identifier")
        groups.setdefault("d" + match[3], []).append({
            "source_row": line_number, "utterance_id": name,
            "speaker": speaker, "turn_index": int(match[1]), "text": text,
        })
    selected = sorted(groups, key=lambda name: digest(name.encode()))[:24]
    if len(selected) != 24:
        raise ValueError("not enough DailyTalk conversations")
    result = []
    for conversation in selected:
        rows = sorted(groups[conversation], key=lambda row: row["turn_index"])
        if len(rows) < 3 or rows[0]["turn_index"] != 0:
            raise ValueError("selected DailyTalk conversation lacks initial history")
        item = packet("dailytalk", conversation, url, rows, 2,
                      "conversation_sha256_order;third_turn", digest(data))
        item["source_speaker_ids"] = ["dailytalk:0", "dailytalk:1"]
        result.append(item)
    return result


def read_swda(reader: SourceReader) -> list[dict]:
    url = f"https://raw.githubusercontent.com/cgpotts/swda/{SWDA_REVISION}/swda.zip"
    if SWDA_ZIP_SIZE > 32 * MAX_READ:
        raise ValueError("ZIP structure memory budget exceeded")
    tail_start = SWDA_ZIP_SIZE - 65_557
    tail = reader.get(url, (tail_start, SWDA_ZIP_SIZE - 1))
    position = tail.rfind(b"PK\x05\x06")
    if position < 0:
        raise ValueError("ZIP central directory footer missing")
    footer = struct.unpack_from("<4s4H2LH", tail, position)
    _, disk, directory_disk, disk_count, total_count, size, offset, comment = footer
    if disk or directory_disk or disk_count != total_count or size > MAX_READ:
        raise ValueError("unsupported ZIP directory")
    if position + 22 + comment != len(tail) or offset + size > tail_start + position:
        raise ValueError("invalid ZIP directory extent")
    sparse = bytearray(SWDA_ZIP_SIZE)
    sparse[tail_start:] = tail
    sparse[offset:offset + size] = reader.get(url, (offset, offset + size - 1))
    archive = zipfile.ZipFile(io.BytesIO(sparse))
    members = sorted((item for item in archive.infolist()
                      if re.fullmatch(r"swda/sw\d+utt/sw_\d+_\d+\.utt\.csv", item.filename)),
                     key=lambda item: item.filename)[:24]
    if len(members) != 24:
        raise ValueError("not enough SwDA conversation members")
    def read_member(member: zipfile.ZipInfo) -> bytes:
        if member.file_size > MAX_READ or member.compress_size + 4096 > MAX_READ:
            raise ValueError("ZIP member inspection budget exceeded")
        start = member.header_offset
        end = min(SWDA_ZIP_SIZE - 1, start + 30 + 4096 + member.compress_size - 1)
        sparse[start:end + 1] = reader.get(url, (start, end))
        with zipfile.ZipFile(io.BytesIO(sparse)) as complete:
            return complete.read(member.filename)

    metadata_bytes = read_member(archive.getinfo("swda/swda-metadata.csv"))
    metadata = {row["conversation_no"]: row for row in
                csv.DictReader(io.StringIO(metadata_bytes.decode()))}
    desired_tags = [{"b"}, {"%"}, {"qy", "qw"}, {"ar", "arp", "aap"}]
    result = []
    for index, member in enumerate(members):
        data = read_member(member)
        rows = []
        for row_number, row in enumerate(csv.DictReader(io.StringIO(data.decode())), 2):
            rows.append({
                "source_row": row_number, "speaker": row["caller"],
                "text": row["text"], "source_act_tag": row["act_tag"],
                "utterance_id": row.get("utterance_index", str(row_number)),
            })
        tags = desired_tags[index % len(desired_tags)]
        candidates = [i for i, row in enumerate(rows[:60])
                      if i >= 2 and row["source_act_tag"].split(",")[0] in tags]
        target = candidates[0] if candidates else 2
        selection = "tags=" + ",".join(sorted(tags)) + (";matched" if candidates else ";fallback")
        conversation = re.search(r"_(\d+)\.utt\.csv$", member.filename)[1]
        item = packet("swda", conversation, url + "#" + member.filename,
                      rows, target, selection, digest(data))
        meta = metadata[conversation]
        item["source_speaker_ids"] = ["switchboard:" + meta[key]
                                      for key in ("from_caller", "to_caller")]
        item["source_topic"] = meta["topic_description"]
        item["metadata_sha256"] = digest(metadata_bytes)
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reader = SourceReader(args.output)
    try:
        packets = read_dailytalk(reader) + read_swda(reader)
        keys = {(item["source"], item["conversation_id"]) for item in packets}
        if len(packets) != 48 or len(keys) != 48:
            raise ValueError("expected 48 unique source conversations")
        (args.output / "packets.json").write_text(
            json.dumps(packets, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": "collected_for_review", "conversations": len(keys),
                          "network_bytes": reader.total, "output": str(args.output)}))
    finally:
        (args.output / "requests.json").write_text(
            json.dumps(reader.ledger, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
