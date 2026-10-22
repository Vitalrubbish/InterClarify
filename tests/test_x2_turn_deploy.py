import hashlib

import numpy as np
import pytest

from scripts.remote import prepare_x2_turn_model, x2_turn_service_probe


def _config() -> dict:
    return {"default_num_delay_tokens": 6, "audio_length_per_tok": 8}


def _tekken(delay_ms: int = 480) -> dict:
    return {
        "audio": {
            "sampling_rate": 16000,
            "frame_rate": 12.5,
            "transcription_delay_ms": delay_ms,
            "audio_encoding_config": {"hop_length": 160, "num_mel_bins": 128},
        }
    }


def test_compute_delay_matches_frozen_values():
    delay = prepare_x2_turn_model.compute_delay(_config(), _tekken())
    assert delay["delay_tokens"] == 6
    assert delay["ms_per_token"] == 80.0
    assert delay["transcription_delay_ms"] == 480


def test_compute_delay_rejects_inconsistent_sources():
    with pytest.raises(ValueError):
        prepare_x2_turn_model.compute_delay(_config(), _tekken(delay_ms=400))


def test_verify_snapshot_checks_hash_and_size(tmp_path):
    payload = b"weights"
    (tmp_path / "model.safetensors").write_bytes(payload)
    expected = {
        "model.safetensors": {
            "size": len(payload),
            "lfs_sha256": hashlib.sha256(payload).hexdigest(),
        }
    }
    names = ["model.safetensors"]
    result = prepare_x2_turn_model.verify_snapshot(tmp_path, expected, names)
    assert result[0]["verified_sha256"] is True

    expected["model.safetensors"]["lfs_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepare_x2_turn_model.verify_snapshot(tmp_path, expected, names)

    expected["model.safetensors"] = {"size": 1, "lfs_sha256": None}
    with pytest.raises(ValueError):
        prepare_x2_turn_model.verify_snapshot(tmp_path, expected, names)


def _turn(monotonic: float, turn_id: int, name: str, index: int) -> dict:
    return {
        "monotonic": monotonic,
        "utc": "2026-10-22T00:00:00+00:00",
        "event": {
            "type": "turn.delta",
            "turn_id": turn_id,
            "turn_class": name,
            "frame_index": index,
            "probs": [0.0] * 6,
        },
    }


def _text(monotonic: float, delta: str) -> dict:
    return {
        "monotonic": monotonic,
        "utc": "2026-10-22T00:00:00+00:00",
        "event": {"type": "transcription.delta", "delta": delta},
    }


def test_summarize_counts_complete_before_and_after_end():
    events = [
        _text(0.2, "hello "),
        _text(0.4, "world"),
        _turn(0.5, 35, "idle", 0),
        _turn(0.9, 38, "turn_end", 1),
        _turn(1.2, 38, "turn_end", 2),
    ]
    summary = x2_turn_service_probe.summarize(events, t_start=0.0, t_end=1.0)
    assert summary["transcript"] == "hello world"
    assert summary["complete"]["count"] == 2
    assert summary["complete"]["before_end_count"] == 1
    assert summary["complete"]["after_end_count"] == 1
    assert summary["complete"]["first_after_end_ms"] == 200.0
    assert summary["turn_class_counts"] == {"idle": 1, "turn_end": 2}


def test_summarize_leaves_delay_null_when_complete_is_absent():
    summary = x2_turn_service_probe.summarize([_turn(0.5, 35, "idle", 0)], 0.0, 1.0)
    assert summary["complete"]["seen"] is False
    assert summary["complete"]["first_after_end_ms"] is None


def test_summarize_rejects_mismatched_class_names():
    with pytest.raises(ValueError):
        x2_turn_service_probe.summarize([_turn(0.5, 38, "idle", 0)], 0.0, 1.0)


def test_chunk_pcm_keeps_tail_chunk():
    pcm = np.arange(x2_turn_service_probe.CHUNK_SAMPLES + 10, dtype=np.int16)
    chunks = x2_turn_service_probe.chunk_pcm(pcm)
    assert [len(chunk) for chunk in chunks] == [
        x2_turn_service_probe.CHUNK_SAMPLES,
        10,
    ]
    assert np.array_equal(np.concatenate(chunks), pcm)
