#!/usr/bin/env python3
"""Run the official FDB v1.0 alignment and GPT judge on an existing A4 FDB output tree.

The official scorer expects `output.json` next to every `output.wav`. It produces
that file with NeMo parakeet word timestamps and then rates the post-interruption
answer with an OpenAI-compatible chat model. This runner keeps the upstream
scripts unmodified except for an optional judge-model substitution inside a work
copy, loads credentials from the project credential file, and writes a summary.

Credentials are read at runtime and never written to logs.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

JUDGE_MODEL_PATTERN = 'MODEL_NAME = "gpt-4-turbo"'
DEFAULT_BASE_URL = "https://api-2.xi-ai.cn/v1"
DEFAULT_JUDGE_MODEL = "gpt-4-turbo"
JUDGE_TASKS = ("user_interruption", "behavior")
# The official entry points live in these two directories; copying only them keeps
# the work copy small and avoids the upstream node_modules tree, which contains
# dangling symlinks that break a plain recursive copy.
WORK_SUBDIRS = ("get_transcript", "evaluation")
AVERAGE_PATTERNS = {
    "average_rating": re.compile(r"Average rating:\s*([0-9.]+)"),
    "average_take_turn": re.compile(r"Average take turn:\s*([0-9.]+)"),
    "average_latency": re.compile(r"Average latency:\s*([-0-9.]+)"),
}


def read_api_key(path: pathlib.Path, environ: dict[str, str]) -> str:
    """Return the judge API key from an explicit file or the environment.

    Parameters
    ----------
    path : pathlib.Path
        Project credential file holding the raw key.
    environ : dict[str, str]
        Process environment, used as a fallback source.

    Returns
    -------
    str
        Non-empty API key.

    Raises
    ------
    SystemExit
        Raised when no non-empty key is available.
    """
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    key = environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    raise SystemExit(f"no judge API key: fill {path} or set OPENAI_API_KEY")


def git_commit(repo: pathlib.Path) -> str:
    """Return the recorded upstream commit of an FDB checkout."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def prepare_work_repo(repo: pathlib.Path, out: pathlib.Path, judge_model: str) -> pathlib.Path:
    """Copy the pinned FDB version into the run directory and set the judge model.

    Parameters
    ----------
    repo : pathlib.Path
        Full-Duplex-Bench checkout.
    out : pathlib.Path
        Run output directory that hosts the work copy.
    judge_model : str
        Chat model name the upstream script should call.

    Returns
    -------
    pathlib.Path
        Path of the `v1_v1.5` work copy.
    """
    work = out / "fdb_repo" / "v1_v1.5"
    for name in WORK_SUBDIRS:
        source = repo / "v1_v1.5" / name
        if not source.is_dir():
            raise SystemExit(f"missing official FDB script directory: {source}")
        shutil.copytree(
            source, work / name, dirs_exist_ok=True,
            symlinks=True, ignore_dangling_symlinks=True,
        )
    if judge_model != DEFAULT_JUDGE_MODEL:
        target = work / "evaluation" / "eval_user_interruption.py"
        text = target.read_text(encoding="utf-8")
        replaced = text.replace(
            JUDGE_MODEL_PATTERN, f'MODEL_NAME = "{judge_model}"'
        )
        if replaced == text:
            raise SystemExit(f"could not set judge model in {target}")
        target.write_text(replaced, encoding="utf-8")
    return work


def run_step(name: str, command: list[str], log_path: pathlib.Path, extra_env: dict[str, str],
             cwd: pathlib.Path | None = None) -> int:
    """Run one official command, tee its output into a log, and return the exit code."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(extra_env)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(command)}\n")
        log.flush()
        process = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=environment, cwd=str(cwd) if cwd else None, check=False,
        )
        log.write(process.stdout)
    print(f"[llm_judge] step={name} rc={process.returncode} log={log_path}")
    return process.returncode


def parse_scores(log_path: pathlib.Path) -> dict[str, float]:
    """Extract the official aggregate lines from a judge log."""
    if not log_path.is_file():
        return {}
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    scores: dict[str, float] = {}
    for name, pattern in AVERAGE_PATTERNS.items():
        match = pattern.search(text)
        if match:
            scores[name] = float(match.group(1))
    return scores


def main() -> int:
    """Align one FDB subset and optionally run the GPT judge on it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fdb-repo", type=pathlib.Path,
                        default=pathlib.Path("/hpc_stor03/sjtu_home/xuan.zhang/Full-Duplex-Bench"))
    parser.add_argument("--root-dir", type=pathlib.Path, required=True,
                        help="FDB subset output directory containing <sample>/output.wav")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="directory for logs and the summary")
    parser.add_argument("--task", default="user_interruption")
    parser.add_argument("--align-task", default=None,
                        help="official asr.py task; defaults to user_interruption for that axis, else default")
    parser.add_argument("--env", default="full-duplex-bench", help="conda environment holding NeMo")
    parser.add_argument("--audio-name", default="output.wav")
    parser.add_argument("--key-file", type=pathlib.Path, default=None)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--judge-model", default=os.environ.get("DUPLEX_A4_FDB_JUDGE_MODEL", DEFAULT_JUDGE_MODEL))
    parser.add_argument("--gpus", default="0", help="CUDA_VISIBLE_DEVICES for the alignment step")
    parser.add_argument("--hf-online", action="store_true", help="allow Hugging Face downloads")
    parser.add_argument("--skip-align", action="store_true")
    parser.add_argument("--skip-judge", action="store_true")
    args = parser.parse_args()

    root = args.root_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"missing FDB output root: {root}")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    key_file = (args.key_file or pathlib.Path(__file__).resolve().parents[2] / "openai_api.txt").resolve()

    needs_judge = args.task in JUDGE_TASKS and not args.skip_judge
    extra_env = {"CUDA_VISIBLE_DEVICES": args.gpus, "TOKENIZERS_PARALLELISM": "false"}
    if not args.hf_online:
        extra_env["HF_HUB_OFFLINE"] = "1"
    if needs_judge:
        # The official evaluate.py builds OpenAI(api_key=...) from the environment.
        extra_env["OPENAI_API_KEY"] = read_api_key(key_file, os.environ)
        extra_env["OPENAI_BASE_URL"] = args.base_url

    work = prepare_work_repo(args.fdb_repo, out, args.judge_model)
    summary: dict[str, object] = {
        "task": args.task,
        "root_dir": str(root),
        "fdb_repo": str(args.fdb_repo),
        "fdb_commit": git_commit(args.fdb_repo),
        "judge_model": args.judge_model if needs_judge else None,
        "judge_base_url": args.base_url if needs_judge else None,
        "audio_name": args.audio_name,
    }

    align_rc = 0
    align_task = args.align_task or ("user_interruption" if args.task == "user_interruption" else "default")
    summary["align_task"] = align_task
    if not args.skip_align:
        align_rc = run_step(
            "align",
            ["conda", "run", "--no-capture-output", "-n", args.env, "python",
             str(work / "get_transcript" / "asr.py"), "--root_dir", str(root),
             "--task", align_task, "--audio_name", args.audio_name],
            out / f"align_{align_task}.log", extra_env,
        )
    summary["align_rc"] = align_rc

    judge_rc = 0
    if needs_judge and align_rc == 0:
        judge_log = out / f"judge_{args.task}.log"
        judge_rc = run_step(
            "judge",
            ["conda", "run", "--no-capture-output", "-n", args.env, "python",
             str(work / "evaluation" / "evaluate.py"), "--task", args.task, "--root_dir", str(root)],
            judge_log, extra_env, cwd=out,
        )
        summary["judge_rc"] = judge_rc
        summary.update(parse_scores(judge_log))
    summary["ratings"] = sorted(
        str(path.relative_to(root).parent) for path in root.rglob("rating.json")
    )
    summary["aligned_samples"] = sorted(
        str(path.relative_to(root).parent) for path in root.rglob(
            args.audio_name.rsplit(".", 1)[0] + ".json"
        )
    )
    (out / "llm_judge_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "ratings"}, ensure_ascii=False))
    if align_rc != 0 or judge_rc != 0:
        return 1
    if needs_judge and not summary["ratings"]:
        print("[llm_judge] no rating.json was produced", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
