# Archived implementation

Updated: 2026-10-30. This directory holds the implementation of the retired TextTurn, VoxTurn and XTurnix routes. The active SoulX-Duplug route lives in `scripts/runtime/` and `scripts/remote/`.

## Layout

| Path | Content |
| --- | --- |
| `configs/` | Frozen route configurations |
| `scripts/analysis/` | Dataset audits and diagnostics |
| `scripts/remote/` | Cluster job entrypoints, replay and scoring drivers |
| `scripts/runtime/` | TextTurn context assembler |
| `tests/` | Contract tests kept with the archived implementation |

The archived tests resolve `parents[1]` to this directory, so their `configs/` and `scripts/` paths still work when run from here. They are outside the repository's default pytest collection. Run them explicitly only when tracing a historical result:

```bash
cd archive
python -m pytest tests
```

Some tests still read local `artifacts/` or model assets that are not committed. Missing large assets should fail loudly rather than be replaced. Archived cluster wrappers are retained for provenance and are not expected to run against the current remote layout.

Documentation for these files is under `docs/archive/`; route narratives are under `docs/archive/dev/`. Historical work orders are kept locally in `docs/issue/archive/` and are not tracked by Git.
