#!/usr/bin/env bash
# Prepare round-one test audio from the project scenario assets.
#
# Converts the 24 kHz float32 scenario WAVs into 16 kHz mono PCM16 WAVs under
# $XTALK_ROUND1_ROOT/audio/ and writes a manifest with source, duration,
# checksums, and transcript status. ASR input requires 16 kHz mono; the TTS
# reference keeps the same rate so both sides agree on the audio format.
#
# Usage:
#   bash scripts/remote/prepare_xtalk_round1_audio.sh
set -euo pipefail

REPO_ROOT="$(realpath "$(dirname "${BASH_SOURCE[0]}")/../..")"
XTALK_ROUND1_ROOT="${XTALK_ROUND1_ROOT:-/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1}"
AUDIO_ROOT="$XTALK_ROUND1_ROOT/audio"
SCENARIOS="$AUDIO_ROOT/scenarios"
SOURCE_ASSETS="$REPO_ROOT/assets/p1_2_scenarios"

mkdir -p "$SCENARIOS"

convert() {
  local src="$1" dst="$2"
  # -nostdin: ffmpeg must not consume the loop's stdin (find | sort pipe).
  ffmpeg -nostdin -y -v error -i "$src" -ar 16000 -ac 1 -c:a pcm_s16le "$dst"
  echo "[audio] $dst <- $src"
}

# ASR smoke input: a natural Chinese question.
convert "$SOURCE_ASSETS/barge_in_stop/01_question.wav" "$AUDIO_ROOT/request.wav"
# TTS voice reference: the longest clean clip.
convert "$SOURCE_ASSETS/backchannel_long_speech/01_long_speech.wav" "$AUDIO_ROOT/reference.wav"

# Full scenario set for later full-chain testing.
while IFS= read -r -d '' src; do
  rel="$(realpath --relative-to="$SOURCE_ASSETS" "$src")"
  name="$(echo "$rel" | tr '/' '_')"
  convert "$src" "$SCENARIOS/$name"
done < <(find "$SOURCE_ASSETS" -name '*.wav' -print0 | sort -z)

python3 - "$AUDIO_ROOT" "$SOURCE_ASSETS" <<'PY'
import hashlib
import json
import pathlib
import sys
import wave

audio_root = pathlib.Path(sys.argv[1])
source_assets = pathlib.Path(sys.argv[2])
entries = []
for path in sorted(audio_root.rglob("*.wav")):
    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        frames = wav.getnframes()
    if rate != 16000:
        raise SystemExit(f"{path} is not 16 kHz")
    rel_source = None
    if path.name == "request.wav":
        rel_source = "barge_in_stop/01_question.wav"
    elif path.name == "reference.wav":
        rel_source = "backchannel_long_speech/01_long_speech.wav"
    elif path.parent.name == "scenarios":
        rel_source = path.name.replace("_", "/", 1)
    entries.append({
        "file": str(path.relative_to(audio_root)),
        "source": str(source_assets / rel_source) if rel_source else None,
        "sample_rate": rate,
        "duration_seconds": round(frames / rate, 3),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "transcript": None,
        "transcript_status": "pending_manual_annotation",
    })
manifest = {
    "note": ("Scenario clips are converted from the project assets/p1_2_scenarios "
             "recordings (24 kHz float32 -> 16 kHz mono PCM16). Human transcripts "
             "are pending manual annotation; ASR outputs are machine reference only."),
    "clips": entries,
}
out = audio_root / "manifest.json"
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[audio] manifest written: {out} ({len(entries)} clips)")
PY

echo "[audio] audio root: $AUDIO_ROOT"
