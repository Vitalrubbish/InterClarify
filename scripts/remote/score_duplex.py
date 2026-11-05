"""Align generated audio with frozen Parakeet and apply audited FDB v1 rules."""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback


SCORING_COMMIT = "3e799c45a045256f47d5f1c9cda90157e2d2ec9e"
ALIGNMENT_VERSION = "input_duration_before_asr_v3"
SUBSETS = {"candor_turn_taking", "candor_pause_handling", "synthetic_pause_handling",
           "synthetic_user_interruption"}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def scoring_view(audio_path, target, input_info):
    import soundfile as sf

    with sf.SoundFile(audio_path) as source:
        frames = round(input_info.frames * source.samplerate / input_info.samplerate)
        if frames <= 0 or frames > source.frames:
            raise ValueError("Recording does not cover the complete input-duration scoring window")
        waveform = source.read(frames, dtype="float32", always_2d=False)
        rate = source.samplerate
    sf.write(target, waveform, rate, subtype="PCM_16")
    return {"frames": frames, "sample_rate": rate, "seconds": frames / rate,
            "sha256": digest(target)}


def validate_recording(folder, recording):
    import numpy as np
    import soundfile as sf

    for name, key in (("output.wav", "audio_sha256"), ("playback_frames.jsonl", "frames_sha256"),
                      ("events.jsonl", "events_sha256")):
        if digest(folder / name) != recording[key]:
            raise ValueError("Live playback recording provenance mismatch")
    if recording.get("kind") != "live_monotonic_playback_capture" or recording.get("posthoc_audio_synthesis") is not False:
        raise ValueError("Scoring requires the actual live playback recording")
    audio, rate = sf.read(folder / "output.wav", dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Invalid live playback recording")
    end = 0
    with (folder / "playback_frames.jsonl").open() as stream:
        for line in stream:
            frame = json.loads(line)
            start, count = frame["start_sample"], frame["samples"]
            if (not isinstance(start, int) or not isinstance(count, int) or start < end
                    or not 0 < count <= 320 or start + count > len(audio)
                    or not math.isfinite(frame["time"]) or round(frame["time"] * rate) != start):
                raise ValueError("Invalid live playback frame ledger")
            if audio[end:start].any():
                raise ValueError("Audio exists outside the recorded playback frames")
            end = start + count
    if audio[end:].any():
        raise ValueError("Audio exists after the final recorded playback frame")


def behavior(chunks, origin=None):
    if not chunks:
        return {"tor": 0, "latency": None}
    previous = -1
    for item in chunks:
        start, end = item["timestamp"]
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
                and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end and start >= previous):
            raise ValueError("Invalid ASR word timestamps")
        previous = start
    duration = chunks[-1]["timestamp"][1] - chunks[0]["timestamp"][0]
    success = int(duration >= 1 or len(chunks) > 3)
    latency = max(0, chunks[0]["timestamp"][0] - origin) if success and origin is not None else None
    return {"tor": success, "latency": latency}


def align(model, audio_path, offset=0):
    import soundfile as sf

    waveform, sr = sf.read(audio_path, dtype="float32")
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    if not math.isfinite(offset) or offset < 0 or not sr > 0:
        raise ValueError("Invalid scoring crop")
    if not len(waveform):
        raise ValueError("Recorded audio file has no timeline")
    import numpy as np

    if not np.isfinite(waveform).all():
        raise ValueError("Recorded audio contains nonfinite samples")
    waveform = waveform[int(offset * sr):]
    if not len(waveform):
        return {"text": "", "chunks": []}
    if not waveform.any():
        return {"text": "", "chunks": []}
    with tempfile.NamedTemporaryFile(suffix=".wav") as temporary:
        sf.write(temporary.name, waveform, sr)
        result = model.transcribe([temporary.name], timestamps=True)[0]
    timestamps = getattr(result, "timestamp", None) or {}
    words = timestamps.get("word", [])
    if getattr(result, "text", "").strip() and not words:
        raise ValueError("Nonempty ASR text has no word timestamps")
    chunks = [{"text": word["word"], "timestamp": [float(word["start"]) + offset,
                                                        float(word["end"]) + offset]} for word in words]
    behavior(chunks)
    return {"text": " ".join(word["text"] for word in chunks).strip(), "chunks": chunks}


def compare_official(repository, subset, folder, expected):
    if subset == "synthetic_user_interruption":
        return compare_interruption_official(repository, folder, expected)
    filename = "eval_smooth_turn_taking.py" if subset == "candor_turn_taking" else "eval_pause_handling.py"
    function = "eval_smooth_turn_taking" if subset == "candor_turn_taking" else "eval_pause_handling"
    source = repository / "v1_v1.5/evaluation" / filename
    spec = importlib.util.spec_from_file_location("frozen_fdb_evaluator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = io.StringIO()
    error = None
    with redirect_stdout(captured):
        try:
            getattr(module, function)(str(folder))
        except ZeroDivisionError:
            if expected["latency_n"] != 0:
                raise
            error = "Official script divides by zero with no successful latency samples"
    output = captured.getvalue()
    if not error:
        import re

        tor = re.search(r"Average take turn:\s*([0-9.eE+-]+)", output)
        if not tor or abs(float(tor.group(1)) - expected["tor"]) > 1e-9:
            raise ValueError("Audited TOR differs from the frozen official script")
        if subset == "candor_turn_taking":
            latency = re.search(r"Average latency:\s*([0-9.eE+-]+)", output)
            if not latency or abs(float(latency.group(1)) - expected["latency_mean"]) > 1e-9:
                raise ValueError("Audited RL differs from the frozen official script")
    return {"source_sha256": digest(source), "stdout": output, "exception": error}


def compare_interruption_official(repository, folder, expected):
    source = repository / "v1_v1.5/evaluation/eval_user_interruption.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "eval_user_interruption")
    loop = next(node for node in function.body if isinstance(node, ast.For)
                and any(isinstance(child, ast.While) for child in node.body))
    body = next(node for node in loop.body if isinstance(node, ast.While)).body
    start = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "TOR" for t in node.targets))
    finish = next(i for i, node in enumerate(body[start:], start) if isinstance(node, ast.Expr)
                  and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                  and isinstance(node.value.func.value, ast.Name)
                  and node.value.func.value.id == "take_turn_list")
    metric = compile(ast.Module(body=body[start:finish + 1], type_ignores=[]), str(source), "exec")
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    tors, latencies = [], []
    for sample in sorted(folder.iterdir()):
        chunks = json.loads((sample / "output.json").read_text())["chunks"]
        origin = json.loads((sample / "interrupt.json").read_text())[0]["timestamp"][1]
        scope = {**constants, "segments_cw": chunks, "out_after_interrupt": {"chunks": chunks},
                 "input_end_time": origin, "take_turn_list": []}
        # Execute the frozen metric block verbatim, excluding the external relevance judge.
        exec(metric, scope)
        tor, latency = scope["TOR"], scope["latency"]
        tors.append(tor)
        if tor:
            latencies.append(max(0, latency))
    official = {"n": len(tors), "tor": sum(tors) / len(tors), "latency_n": len(latencies),
                "latency_mean": sum(latencies) / len(latencies) if latencies else None}
    for key, value in official.items():
        target = expected[key]
        if (value is None) != (target is None) or (value is not None and abs(value - target) > 1e-9):
            raise ValueError("Audited interruption metric differs from the frozen official metric block")
    return {"source_sha256": digest(source), "method": "frozen_official_tor_latency_block_without_judge",
            "metric_lines": [body[start].lineno, body[finish].end_lineno], "metrics": official,
            "full_official_entrypoint_called": False}


def score_run(args, model, model_hash, repository):
    if args.output.resolve().is_relative_to(args.run.resolve()):
        raise ValueError("Scoring output must be separate from the immutable inference run")
    config = json.loads((args.run / "config.json").read_text())
    summary = json.loads((args.run / "summary.json").read_text())
    if config["stage"] not in {"pilot", "full"} or not summary["passed"]:
        raise ValueError("Only a complete run with no infrastructure failures can be scored")
    if any(s["subset"] == "icc_backchannel" for s in config["samples"]):
        raise ValueError("ICC requires its separate frequency/JSD evaluator")
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    controllers, samples = config["controllers"], config["samples"]
    if (not controllers or len(set(controllers)) != len(controllers)
            or not set(controllers) <= {"xturnix", "soulx"} or not samples):
        raise ValueError("Invalid or empty scoring plan")
    planned = [(c, s["subset"], s["id"]) for c in controllers for s in samples]
    actual = [(r["controller"], r["subset"], r["id"]) for r in summary["results"]]
    if (len(set(planned)) != len(planned) or len(actual) != len(planned) or set(actual) != set(planned)
            or summary.get("planned_samples") != len(planned) or summary["config_sha256"] != config_hash
            or any(not r["passed"] or r["config_sha256"] != config_hash for r in summary["results"])):
        raise ValueError("Run summary differs from the complete frozen plan")
    manifest_path = args.root / "inspection/frozen-20261027-r1/fdb_inputs.json"
    manifest = json.loads(manifest_path.read_text())
    frozen = {(row["subset"], row["id"]): row for row in manifest["records"]}
    rows = []
    input_metadata = {}
    for controller in config["controllers"]:
        for sample in config["samples"]:
            subset, identifier = sample["subset"], sample["id"]
            if subset not in SUBSETS or not isinstance(identifier, str) or Path(identifier).name != identifier:
                raise ValueError("Invalid scoring sample identity")
            folder = args.run / controller / subset / identifier
            result = json.loads((folder / "result.json").read_text())
            if (not result["passed"] or result["input_sha256"] != sample["sha256"]
                    or result["config_sha256"] != config_hash
                    or (result["controller"], result["subset"], result["id"]) != (controller, subset, identifier)):
                raise ValueError("Missing, failed or mismatched sample; preserve the planned denominator")
            original = frozen[(subset, identifier)]
            if sample["sha256"] != original["files"]["input.wav"]["sha256"]:
                raise ValueError("Run input differs from the frozen dataset")
            input_audio = Path(manifest["root"]) / subset / identifier / "input.wav"
            if (subset, identifier) not in input_metadata:
                import soundfile as sf

                if digest(input_audio) != sample["sha256"]:
                    raise ValueError("Input duration source differs from the frozen audio")
                input_metadata[(subset, identifier)] = sf.info(input_audio)
            input_info = input_metadata[(subset, identifier)]
            label_name = "turn_taking.json" if subset == "candor_turn_taking" else (
                "interrupt.json" if subset == "synthetic_user_interruption" else "pause.json")
            label = Path(manifest["root"]) / subset / identifier / label_name
            if digest(label) != original["files"][label_name]["sha256"]:
                raise ValueError("Scoring annotation differs from the frozen input manifest")
            workspace = args.output / "alignments" / controller / subset / identifier
            workspace.mkdir(parents=True, exist_ok=True)
            linked = workspace / label_name
            if not linked.exists():
                linked.symlink_to(label)
            elif linked.resolve() != label.resolve():
                raise ValueError("Preserve a conflicting scoring annotation")
            metadata = json.loads(label.read_text())
            offset = metadata[0]["timestamp"][1] if subset == "synthetic_user_interruption" else 0
            origin = metadata[0]["timestamp"][0] if subset == "candor_turn_taking" else (
                offset if subset == "synthetic_user_interruption" else None)
            audio = folder / "output.wav"
            recording = result.get("recording")
            if recording:
                validate_recording(folder, recording)
            if config.get("recording_policy") and not recording:
                raise ValueError("Run declares live capture but has no recording evidence")
            stamp = {"audio_sha256": digest(audio), "scoring_model_sha256": model_hash,
                     "offset": offset, "annotation_sha256": digest(label),
                     "alignment_version": ALIGNMENT_VERSION, "config_sha256": config_hash,
                     "scoring_window": "zero_to_frozen_input_end", "input_sha256": sample["sha256"],
                     "input_frames": input_info.frames, "input_sample_rate": input_info.samplerate}
            cached = workspace / "alignment_manifest.json"
            transcript_path = workspace / "output.json"
            view = workspace / "output.wav"
            if transcript_path.exists():
                saved = json.loads(cached.read_text()) if cached.exists() else {}
                duration = saved.get("scoring_audio", {})
                if (not view.is_file() or duration.get("sha256") != digest(view)
                        or saved != {**stamp, "scoring_audio": duration, "transcript_sha256": digest(transcript_path)}):
                    raise ValueError("Refuse unverified cached alignment")
                transcript = json.loads(transcript_path.read_text())
            else:
                if cached.exists() or view.exists():
                    raise ValueError("Alignment cache is incomplete; preserve its evidence")
                duration = scoring_view(audio, view, input_info)
                transcript = align(model, view, offset)
                transcript_path.write_text(json.dumps(transcript, indent=2) + "\n")
                cached.write_text(json.dumps({**stamp, "scoring_audio": duration,
                                             "transcript_sha256": digest(transcript_path)}, indent=2) + "\n")
            score = behavior(transcript["chunks"], origin)
            rows.append({"controller": controller, "subset": subset, "id": identifier, **score,
                         "alignment": str(transcript_path),
                         "scoring_audio": str(view), "scoring_seconds": duration["seconds"],
                         "recorded_audio": str(audio), "recording_kind": recording["kind"] if recording else "legacy_playback_frames"})
    aggregates = []
    for controller in config["controllers"]:
        for subset in dict.fromkeys(sample["subset"] for sample in config["samples"]):
            selected = [row for row in rows if row["controller"] == controller and row["subset"] == subset]
            latencies = [row["latency"] for row in selected if row["latency"] is not None]
            aggregate = {"controller": controller, "subset": subset, "n": len(selected),
                         "successes": sum(row["tor"] for row in selected),
                         "tor": sum(row["tor"] for row in selected) / len(selected),
                         "latency_n": len(latencies),
                         "latency_mean": sum(latencies) / len(latencies) if latencies else None}
            aggregate["official_comparison"] = compare_official(
                repository, subset, args.output / "alignments" / controller / subset, aggregate)
            aggregate["reported_metrics"] = ["tor"] if "pause_handling" in subset else ["tor", "latency"]
            aggregates.append(aggregate)
    return {"kind": "pilot_only_not_full_benchmark" if config["stage"] == "pilot" else "full_benchmark_shard",
            "rows": rows, "aggregates": aggregates,
            "n": len(rows), "judge": "excluded_by_user", "backchannel": "excluded_by_user",
            "evaluation_pipeline": "project_adapter_with_frozen_official_metric_checks",
            "scoring_window": "zero_to_frozen_input_end",
            "manifest_sha256": digest(manifest_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe-audio", type=Path)
    group.add_argument("--run", type=Path)
    args = parser.parse_args()
    if not (Path(sys.prefix) / "conda-meta/history").is_file():
        parser.error("Use conda Python")
    if args.run and args.output.resolve().is_relative_to(args.run.resolve()):
        parser.error("Scoring output must be separate from the immutable inference run")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"passed": False, "python": sys.prefix,
              "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}}
    try:
        import torch
        import nemo.collections.asr as nemo_asr

        if torch.cuda.device_count() != 1 or "4090" not in torch.cuda.get_device_name(0):
            raise RuntimeError("One RTX 4090 is required for scoring")
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        torch.cuda.set_per_process_memory_fraction(0.83, 0)
        repository = args.root.parent / "Full-Duplex-Bench"
        commit = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
        if commit != SCORING_COMMIT:
            raise ValueError("Official scoring source commit differs from the freeze")
        if subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain"], text=True).strip():
            raise ValueError("Official scoring working tree differs from its frozen commit")
        verification = json.loads((args.root / "scoring-models/download_verification.json").read_text())
        plan = json.loads((args.root / "scoring-models/download_plan.json").read_text())
        if not verification["passed"]:
            raise ValueError("Scoring model verification failed")
        entry = next(row for row in verification["files"] if row["file"].endswith(".nemo"))
        archive = args.root / "scoring-models/parakeet-tdt" / entry["file"]
        if digest(archive) != entry["sha256"]:
            raise ValueError("Scoring model archive hash mismatch")
        report.update(scoring_commit=commit, model_revision=plan["models"]["parakeet-tdt"]["revision"],
                      model_sha256=entry["sha256"], gpu=torch.cuda.get_device_name(0))
        model = nemo_asr.models.ASRModel.restore_from(str(archive), map_location=torch.device("cuda:0")).eval()
        with torch.inference_mode():
            if args.probe_audio:
                report["probe"] = align(model, args.probe_audio)
                if not report["probe"]["chunks"]:
                    raise ValueError("Scoring probe returned no word alignment")
            else:
                report["scores"] = score_run(args, model, entry["sha256"], repository)
        report["passed"] = True
    except Exception as exc:
        report.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        traceback.print_exc()
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "error": report.get("error")}), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
