"""Parallel per-model snapshot downloader for the round-one lock.

Resolves immutable revisions once (reusing an existing lock), downloads every
model snapshot concurrently into the shared cache, then records snapshot
paths back into models.lock.json with single-writer semantics.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

MODEL_ROOT = Path(sys.argv[1])
CONFIG_PATH = Path(sys.argv[2])

config = __import__("yaml").safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
lock_path = MODEL_ROOT / "models.lock.json"
lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {"models": {}}
api = HfApi()


def resolve(role: str) -> dict:
    requested = config["models"][role]
    entry = lock["models"].get(role)
    if entry is None:
        revision = api.model_info(requested["model_id"], revision=requested["revision"]).sha
        entry = {"model_id": requested["model_id"], "revision": revision, "snapshot_path": None}
        lock["models"][role] = entry
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        assert entry["model_id"] == requested["model_id"]
        assert requested["revision"] is None or requested["revision"] == entry["revision"]
    return entry


def download(role: str) -> tuple[str, str]:
    entry = resolve(role)
    if entry.get("snapshot_path"):
        # Already satisfied (e.g. a local snapshot hash-verified against the
        # locked revision); do not re-download.
        return role, entry["snapshot_path"]
    path = snapshot_download(
        repo_id=entry["model_id"],
        revision=entry["revision"],
        cache_dir=str(MODEL_ROOT / "cache"),
        max_workers=8,
    )
    return role, str(Path(path).resolve())


roles = list(config["models"].keys())
paths: dict[str, str] = {}
with ThreadPoolExecutor(max_workers=len(roles)) as pool:
    for role, path in pool.map(download, roles):
        paths[role] = path
        print(f"[dl] {role}: {path}", flush=True)

for role, path in paths.items():
    lock["models"][role]["snapshot_path"] = path
lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("[dl] lock updated, all snapshots complete", flush=True)
