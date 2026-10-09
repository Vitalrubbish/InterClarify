#!/usr/bin/env python3
"""P0 audio I/O capability probe.

Records the audio input/output conditions required by
``docs/engineering_implementation.md`` section 4.2: devices, sample rate,
channels, block size and echo-cancellation assumptions.

The probe is informational: a headless cluster node legitimately reports zero
devices.  Pass ``--require-devices`` to treat that as a failure, and
``--json-out`` to persist the evidence used by the P0 gate.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def probe(sample_rate: int, chunk_ms: int, assume_aec: bool) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "platform": platform.platform(),
        "target_sample_rate": sample_rate,
        "target_channels": 1,
        "chunk_ms": chunk_ms,
        "suggested_blocksize": int(round(sample_rate * chunk_ms / 1000.0)),
        "sounddevice_available": False,
        "host_apis": [],
        "input_devices": [],
        "output_devices": [],
        "default_input": None,
        "default_output": None,
        "echo_cancellation_assumed": bool(assume_aec),
        "notes": [],
    }

    try:
        import sounddevice as sd
    except Exception as exc:
        report["notes"].append(f"sounddevice unavailable: {type(exc).__name__}: {exc}")
        report["status"] = "NO_AUDIO_BACKEND"
        return report

    report["sounddevice_available"] = True
    try:
        report["host_apis"] = [
            {"index": i, "name": api.get("name"), "devices": len(api.get("devices", []))}
            for i, api in enumerate(sd.query_hostapis())
        ]
        for index, device in enumerate(sd.query_devices()):
            entry = {
                "index": index,
                "name": device.get("name"),
                "max_input_channels": device.get("max_input_channels"),
                "max_output_channels": device.get("max_output_channels"),
                "default_samplerate": device.get("default_samplerate"),
                "hostapi": device.get("hostapi"),
            }
            if int(device.get("max_input_channels", 0)) > 0:
                report["input_devices"].append(entry)
            if int(device.get("max_output_channels", 0)) > 0:
                report["output_devices"].append(entry)
        default_in, default_out = sd.default.device
        report["default_input"] = default_in
        report["default_output"] = default_out
    except Exception as exc:  # pragma: no cover - backend dependent
        report["notes"].append(f"device query failed: {type(exc).__name__}: {exc}")
        report["status"] = "QUERY_ERROR"
        return report

    # sounddevice exposes the WASAPI host API on Windows where OS-level AEC may
    # exist; on Linux/ALSA there is no built-in acoustic echo cancellation.
    aec_capable = any("wasapi" in str(api.get("name", "")).lower() for api in report["host_apis"])
    report["aec_host_api_present"] = aec_capable
    if not aec_capable:
        report["notes"].append(
            "No OS-level AEC host API detected; plan a software echo-suppression step "
            "or use push-to-interrupt for the local profile."
        )
    report["status"] = "OK" if (report["input_devices"] and report["output_devices"]) else "NO_DEVICES"
    return report


def _format_text(report: Dict[str, Any]) -> str:
    lines: List[str] = [f"status: {report['status']}"]
    for key in (
        "platform",
        "target_sample_rate",
        "target_channels",
        "chunk_ms",
        "suggested_blocksize",
        "sounddevice_available",
        "aec_host_api_present",
        "echo_cancellation_assumed",
        "default_input",
        "default_output",
    ):
        if key in report:
            lines.append(f"{key}: {report[key]}")
    lines.append(f"input_devices: {len(report.get('input_devices', []))}")
    for device in report.get("input_devices", []):
        lines.append(
            f"  in{device['index']}: {device['name']} ch={device['max_input_channels']} "
            f"sr={device['default_samplerate']}"
        )
    lines.append(f"output_devices: {len(report.get('output_devices', []))}")
    for device in report.get("output_devices", []):
        lines.append(
            f"  out{device['index']}: {device['name']} ch={device['max_output_channels']} "
            f"sr={device['default_samplerate']}"
        )
    for note in report.get("notes", []):
        lines.append(f"note: {note}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-ms", type=int, default=80)
    parser.add_argument("--assume-aec", action="store_true")
    parser.add_argument("--require-devices", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    report = probe(args.sample_rate, args.chunk_ms, args.assume_aec)
    sys.stdout.write(_format_text(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.require_devices and report["status"] != "OK":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
