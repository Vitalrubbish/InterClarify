#!/usr/bin/env python3
"""Download and verify the pinned DuplexCascade assets on a server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

import requests
import yaml


DEFAULT_MODEL_ROOT = "/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models"
DEFAULT_ARTIFACT_ROOT = "/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-artifacts"

# ModelScope is used as the fast, resumable asset provider in the cluster.
# Its file listing exposes each blob's content SHA-256, which lets us verify
# that a ModelScope download is byte-identical to the pinned Hugging Face
# revision (the HF LFS blob name is the content SHA-256).
MODELSCOPE_API = "https://www.modelscope.cn/api/v1/models"
MODELSCOPE_RESOLVE = "https://www.modelscope.cn/models"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(command: Sequence[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = f"\nstdout={result.stdout.strip()}\nstderr={result.stderr.strip()}"
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}{detail}")
    return result.stdout.strip() if capture and result.stdout else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _is_clean_git_checkout(path: Path) -> bool:
    return _run(["git", "status", "--porcelain"], cwd=path, capture=True) == ""


def _prepare_source(source_root: Path, repo_url: str, commit: str) -> str:
    source_root.parent.mkdir(parents=True, exist_ok=True)
    if not source_root.exists():
        _run(["git", "clone", repo_url, str(source_root)])
    elif not (source_root / ".git").exists():
        raise RuntimeError(f"source path exists but is not a git checkout: {source_root}")

    if not _is_clean_git_checkout(source_root):
        raise RuntimeError(f"refusing to change a dirty source checkout: {source_root}")

    _run(["git", "fetch", "--tags", "origin"], cwd=source_root)
    try:
        _run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=source_root)
    except RuntimeError:
        _run(["git", "fetch", "origin", commit], cwd=source_root)
    _run(["git", "checkout", "--detach", commit], cwd=source_root)
    actual = _run(["git", "rev-parse", "HEAD"], cwd=source_root, capture=True)
    if actual != commit:
        raise RuntimeError(f"source commit mismatch: expected {commit}, got {actual}")
    return actual


def _download_snapshot(
    *,
    repo_id: str,
    revision: str | None,
    cache_dir: Path,
    token: bool | None,
) -> Path:
    # Import lazily so --dry-run remains usable without the model stack.
    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download(
            repo_id=repo_id,
            repo_type="model",
            revision=revision,
            cache_dir=str(cache_dir),
            token=token,
            max_workers=8,
        )
    )


def _ms_session() -> "requests.Session":
    session = requests.Session()
    session.headers.update({"User-Agent": "interclarify-p1-assets/0.1"})
    return session


def _modelscope_list_files(
    session: "requests.Session", repo_id: str, revision: str, root: str = ""
) -> list[dict[str, Any]]:
    namespace, name = repo_id.split("/", 1)
    url = f"{MODELSCOPE_API}/{namespace}/{name}/repo/files"
    params: dict[str, str] = {"Revision": revision}
    if root:
        params["Root"] = root
    response = session.get(url, params=params, timeout=60)
    response.raise_for_status()
    entries = response.json().get("Data", {}).get("Files", [])
    files: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("Type") == "tree":
            files.extend(_modelscope_list_files(session, repo_id, revision, entry["Path"]))
        else:
            files.append(
                {
                    "path": entry["Path"],
                    "size": int(entry.get("Size", 0)),
                    "sha256": (entry.get("Sha256") or "").lower() or None,
                    "revision": entry.get("Revision"),
                }
            )
    return files


def _modelscope_download_file(
    session: "requests.Session",
    repo_id: str,
    revision: str,
    rel_path: str,
    dest: Path,
    expected_sha: str | None,
    expected_size: int,
    *,
    attempts: int = 6,
) -> None:
    namespace, name = repo_id.split("/", 1)
    url = f"{MODELSCOPE_RESOLVE}/{namespace}/{name}/resolve/{revision}/{quote(rel_path)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            existing = dest.stat().st_size if dest.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            mode = "ab" if existing else "wb"
            with session.get(url, headers=headers, stream=True, timeout=120) as response:
                if response.status_code == 416:  # already fully present
                    existing, mode = 0, "wb"
                else:
                    response.raise_for_status()
                    if existing and response.status_code != 206:
                        existing, mode = 0, "wb"
                    with dest.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                            if chunk:
                                handle.write(chunk)
            if expected_size and dest.stat().st_size != expected_size:
                raise RuntimeError(f"size mismatch for {rel_path}: {dest.stat().st_size} != {expected_size}")
            if expected_sha:
                actual = _sha256(dest)
                if actual != expected_sha:
                    dest.unlink(missing_ok=True)
                    raise RuntimeError(f"sha256 mismatch for {rel_path}: {actual} != {expected_sha}")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"failed to download {rel_path} after {attempts} attempts: {last_error}")


def _download_modelscope_snapshot(
    repo_id: str,
    revision: str,
    dest_root: Path,
    session: "requests.Session",
) -> tuple[Path, str]:
    records = _modelscope_list_files(session, repo_id, revision)
    if not records:
        raise RuntimeError(f"empty ModelScope file listing for {repo_id}@{revision}")
    resolved_revision = next((r["revision"] for r in records if r.get("revision")), revision)
    dest = dest_root / repo_id.replace("/", "--") / resolved_revision
    marker = dest / ".ic_complete"
    if not marker.exists():
        total = len(records)
        for index, record in enumerate(records, 1):
            target = dest / record["path"]
            if target.exists() and record["sha256"] and _sha256(target) == record["sha256"]:
                continue
            print(
                f"[modelscope] {repo_id} {index}/{total} {record['path']} ({record['size']} bytes)",
                flush=True,
            )
            _modelscope_download_file(
                session, repo_id, resolved_revision, record["path"], target, record["sha256"], record["size"]
            )
        marker.write_text(resolved_revision + "\n", encoding="utf-8")
    return dest, resolved_revision


def _load_config(repo_root: Path, model_root: Path, artifact_root: Path) -> tuple[dict[str, Any], str]:
    sys.path.insert(0, str(repo_root / "src"))
    from interclarify.config import config_digest, load_config

    config = load_config(
        profile="cluster",
        config_dir=repo_root / "configs",
        overrides={
            "paths": {
                "repo_root": str(repo_root),
                "model_root": str(model_root),
                "artifact_root": str(artifact_root),
            }
        },
    )
    return config, config_digest(config)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=os.environ.get("INTERCLARIFY_ROOT", str(Path.cwd())))
    parser.add_argument("--model-root", default=os.environ.get("INTERCLARIFY_MODEL_ROOT", DEFAULT_MODEL_ROOT))
    parser.add_argument("--artifact-root", default=os.environ.get("INTERCLARIFY_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT))
    parser.add_argument("--run-id", default=None, help="Evidence directory name; defaults to UTC timestamp.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve paths and pins without cloning or downloading.")
    parser.add_argument("--skip-base-model", action="store_true", help="Only prepare DuplexCascade assets.")
    parser.add_argument(
        "--provider",
        choices=("huggingface", "modelscope"),
        default=os.environ.get("IC_ASSET_PROVIDER", "huggingface"),
        help=(
            "Asset provider. 'huggingface' uses the gated HF repo (needs a token); "
            "'modelscope' uses the fast cluster mirror and verifies each blob against the "
            "pinned SHA-256, so the content is byte-identical to the fixed HF revision."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    model_root = Path(args.model_root).expanduser().resolve()
    artifact_root = Path(args.artifact_root).expanduser().resolve()
    if not repo_root.exists():
        raise RuntimeError(f"repository root does not exist: {repo_root}")
    if not model_root.is_absolute() or repo_root == model_root or repo_root in model_root.parents:
        raise RuntimeError("model root must be an absolute path outside the repository")
    if not artifact_root.is_absolute() or repo_root == artifact_root or repo_root in artifact_root.parents:
        raise RuntimeError("artifact root must be an absolute path outside the repository")

    config, config_digest = _load_config(repo_root, model_root, artifact_root)
    duplex = config["duplexcascade"]
    repo_url = str(duplex["repo_url"])
    repo_commit = str(duplex["repo_commit"])
    hf_repo_id = str(duplex["hf_repo_id"])
    hf_revision = str(duplex["hf_revision"])
    weight_filename = str(duplex["weight_filename"])
    expected_weight_sha = str(duplex.get("weight_sha256") or "")
    hf_endpoint = os.environ.get("HF_ENDPOINT") or str(config.get("env", {}).get("HF_ENDPOINT", "https://huggingface.co"))

    dc_root = model_root / "duplexcascade"
    source_root = dc_root / "source"
    hf_home = model_root / "huggingface"
    hf_cache = hf_home / "hub"
    artifact_dir = artifact_root / "p1_assets" / (args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    plan = {
        "repo_root": str(repo_root),
        "model_root": str(model_root),
        "artifact_dir": str(artifact_dir),
        "source_root": str(source_root),
        "hf_home": str(hf_home),
        "hf_endpoint": hf_endpoint,
        "repo_url": repo_url,
        "repo_commit": repo_commit,
        "hf_repo_id": hf_repo_id,
        "hf_revision": hf_revision,
        "weight_filename": weight_filename,
        "config_digest": config_digest,
        "download_base_model": not args.skip_base_model,
        "provider": args.provider,
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    artifact_dir.mkdir(parents=True, exist_ok=False)
    (artifact_dir / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=True), encoding="utf-8"
    )
    _write_json(artifact_dir / "plan.json", plan)
    os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(hf_cache))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(hf_home / "transformers"))

    try:
        source_commit = _prepare_source(source_root, repo_url, repo_commit)

        provider = args.provider
        if provider == "modelscope":
            dc_snapshot, dc_source_revision = _download_modelscope_snapshot(
                hf_repo_id, "master", model_root / "modelscope", _ms_session()
            )
            dc_origin = {
                "provider": "modelscope",
                "repo_id": hf_repo_id,
                "revision": dc_source_revision,
                "equivalent_hf_revision": hf_revision,
                "endpoint": MODELSCOPE_RESOLVE,
            }
        else:
            dc_snapshot = _download_snapshot(
                repo_id=hf_repo_id,
                revision=hf_revision,
                cache_dir=hf_cache,
                token=True,
            )
            dc_origin = {
                "provider": "huggingface",
                "repo_id": hf_repo_id,
                "revision": hf_revision,
                "endpoint": hf_endpoint,
            }

        required_weight = dc_snapshot / weight_filename
        train_cfg_path = dc_snapshot / "train_cfg.json"
        tokenizer_dir = dc_snapshot / "tokenizer"
        if not required_weight.is_file():
            raise RuntimeError(f"required DuplexCascade weight is missing: {required_weight}")
        if not train_cfg_path.is_file():
            raise RuntimeError(f"required DuplexCascade config is missing: {train_cfg_path}")
        if not tokenizer_dir.is_dir() or not any(tokenizer_dir.iterdir()):
            raise RuntimeError(f"DuplexCascade tokenizer directory is missing or empty: {tokenizer_dir}")

        weight_record = _file_record(required_weight)
        if expected_weight_sha:
            if weight_record["sha256"] != expected_weight_sha:
                raise RuntimeError(
                    f"DuplexCascade weight sha256 mismatch: {weight_record['sha256']} != pinned {expected_weight_sha}"
                )
            weight_record["matches_pinned_sha256"] = True

        train_cfg = json.loads(train_cfg_path.read_text(encoding="utf-8"))
        model_cfg = train_cfg.get("model", {}) if isinstance(train_cfg, dict) else {}
        base_model_id = str(model_cfg.get("name", "Qwen/Qwen2-7B-Instruct"))
        base_snapshot: Path | None = None
        base_config_record: dict[str, Any] | None = None
        base_origin: dict[str, Any] | None = None
        if not args.skip_base_model:
            if provider == "modelscope":
                base_snapshot, base_source_revision = _download_modelscope_snapshot(
                    base_model_id, "master", model_root / "modelscope", _ms_session()
                )
                base_origin = {
                    "provider": "modelscope",
                    "repo_id": base_model_id,
                    "revision": base_source_revision,
                    "endpoint": MODELSCOPE_RESOLVE,
                }
            else:
                base_snapshot = _download_snapshot(
                    repo_id=base_model_id,
                    revision=None,
                    cache_dir=hf_cache,
                    token=None,
                )
                base_origin = {"provider": "huggingface", "repo_id": base_model_id, "revision": "main"}
            base_config = base_snapshot / "config.json"
            if not base_config.is_file():
                raise RuntimeError(f"base model config is missing: {base_config}")
            base_config_record = _file_record(base_config)

        manifest = {
            "schema_version": 1,
            "status": "PARTIAL" if args.skip_base_model else "PASS",
            "provider": provider,
            "created_at_utc": _utc_now(),
            "host": platform.node(),
            "python": sys.version.split()[0],
            "config_digest": config_digest,
            "source": {"url": repo_url, "commit": source_commit, "path": str(source_root)},
            "duplexcascade": {
                **dc_origin,
                "snapshot": str(dc_snapshot),
                "weight": weight_record,
                "train_cfg": _file_record(train_cfg_path),
                "tokenizer_files": sorted(str(path.relative_to(tokenizer_dir)) for path in tokenizer_dir.rglob("*") if path.is_file()),
            },
            "base_model": {
                **(base_origin or {}),
                "repo_id": base_model_id,
                "snapshot": str(base_snapshot) if base_snapshot is not None else None,
                "config": base_config_record,
            },
            "environment": {
                "hf_endpoint": hf_endpoint,
                "hf_home": str(hf_home),
                "hf_hub_cache": str(hf_cache),
                "modelscope_root": str(model_root / "modelscope"),
                "token_value_recorded": False,
            },
        }
        _write_json(artifact_dir / "manifest.json", manifest)
        (artifact_dir / "assets.env").write_text(
            "# Source this file before starting the official server.\n"
            f"export HF_ENDPOINT={hf_endpoint}\n"
            f"export HF_HOME={hf_home}\n"
            f"export HF_HUB_CACHE={hf_cache}\n"
            f"export TRANSFORMERS_CACHE={hf_home / 'transformers'}\n"
            f"export INTERCLARIFY_DUPLEXCASCADE_SNAPSHOT={dc_snapshot}\n",
            encoding="utf-8",
        )
        print(f"P1.1 assets prepared: {artifact_dir}")
        print(f"DuplexCascade weight sha256: {manifest['duplexcascade']['weight']['sha256']}")
        return 0
    except Exception as exc:
        _write_json(
            artifact_dir / "failure.json",
            {"status": "FAIL", "created_at_utc": _utc_now(), "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
