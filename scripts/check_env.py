#!/usr/bin/env python3
"""P0 environment acceptance check for InterClarify.

Verifies that the active Python environment can import the core dependency
set, reports their versions, and (optionally) that an expected GPU is visible
to PyTorch.  Writes a machine-readable + human-readable snapshot so the
acceptance evidence can be attached to the P0 gate.

Usage
-----
    python scripts/check_env.py --out experiments/p0_env/environment.txt
    python scripts/check_env.py --require-gpu --json-out experiments/p0_env/env.json

Exit code is the number of hard failures: missing core modules, or a required
GPU that is not visible.  Missing *optional* modules (sounddevice) are reported
but do not fail the check.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List

# module name -> distribution name (for importlib.metadata)
CORE_MODULES: Dict[str, str] = {
    "torch": "torch",
    "transformers": "transformers",
    "peft": "peft",
    "accelerate": "accelerate",
    "huggingface_hub": "huggingface_hub",
    "safetensors": "safetensors",
    "numpy": "numpy",
    "scipy": "scipy",
    "soundfile": "soundfile",
    "librosa": "librosa",
    "websockets": "websockets",
    "msgpack": "msgpack",
    "yaml": "PyYAML",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
}
OPTIONAL_MODULES: Dict[str, str] = {"sounddevice": "sounddevice"}


def _probe(modules: Dict[str, str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for module, dist in modules.items():
        entry: Dict[str, Any] = {}
        try:
            __import__(module)
            entry["import"] = True
        except Exception as exc:  # pragma: no cover - environment dependent
            entry["import"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
        try:
            entry["version"] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            entry["version"] = None
        results[module] = entry
    return results


def _gpu_report() -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "cuda_available": False,
        "device_count": 0,
        "devices": [],
    }
    try:
        import torch
    except Exception as exc:
        report["error"] = f"torch import failed: {exc}"
        return report
    report["torch_version"] = torch.__version__
    report["torch_cuda_version"] = torch.version.cuda
    try:
        report["cuda_available"] = bool(torch.cuda.is_available())
        report["device_count"] = int(torch.cuda.device_count())
        for index in range(report["device_count"]):
            props = torch.cuda.get_device_properties(index)
            report["devices"].append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "capability": f"{props.major}.{props.minor}",
                    "total_memory_gb": round(props.total_memory / 1024**3, 2),
                }
            )
    except Exception as exc:  # pragma: no cover - driver dependent
        report["probe_error"] = repr(exc)
    return report


def run_check(require_gpu: bool) -> Dict[str, Any]:
    core = _probe(CORE_MODULES)
    optional = _probe(OPTIONAL_MODULES)
    missing_core = [m for m, v in core.items() if not v.get("import")]
    gpu = _gpu_report()
    failures = len(missing_core)
    if require_gpu and not gpu.get("cuda_available"):
        failures += 1

    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "hf_endpoint": os.environ.get("HF_ENDPOINT"),
        "core_modules": core,
        "optional_modules": optional,
        "missing_core": missing_core,
        "gpu": gpu,
        "require_gpu": require_gpu,
        "failures": failures,
        "status": "PASS" if failures == 0 else "FAIL",
    }


def _format_text(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"status: {report['status']}")
    lines.append(f"hostname: {report['hostname']}")
    lines.append(f"platform: {report['platform']}")
    lines.append(f"python_version: {report['python_version']}")
    lines.append(f"python_executable: {report['python_executable']}")
    lines.append(f"conda_env: {report['conda_env']}")
    lines.append(f"cuda_visible_devices: {report['cuda_visible_devices']}")
    lines.append(f"hf_endpoint: {report['hf_endpoint']}")
    lines.append("core_modules:")
    for name, entry in sorted(report["core_modules"].items()):
        lines.append(f"  {name}: {entry.get('version')} (import={entry.get('import')})")
    for name, entry in sorted(report["optional_modules"].items()):
        lines.append(f"optional.{name}: {entry.get('version')} (import={entry.get('import')})")
    gpu = report["gpu"]
    lines.append(f"cuda_available: {gpu.get('cuda_available')}")
    lines.append(f"cuda_device_count: {gpu.get('device_count')}")
    lines.append(f"torch_version: {gpu.get('torch_version')}")
    lines.append(f"torch_cuda_version: {gpu.get('torch_cuda_version')}")
    for device in gpu.get("devices", []):
        lines.append(
            f"  gpu{device['index']}: {device['name']} sm_{device['capability'].replace('.', '')} "
            f"{device['total_memory_gb']}GB"
        )
    lines.append(f"missing_core: {report['missing_core']}")
    lines.append(f"failures: {report['failures']}")
    return "\n".join(lines) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write human-readable report to this path")
    parser.add_argument("--json-out", type=Path, help="write JSON report to this path")
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="fail if PyTorch cannot see a CUDA device",
    )
    args = parser.parse_args(argv)

    report = run_check(args.require_gpu)
    text = _format_text(report)
    sys.stdout.write(text)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report["failures"]


if __name__ == "__main__":
    raise SystemExit(main())
