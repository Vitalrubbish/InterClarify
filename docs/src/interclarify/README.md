# 实现文档索引（interclarify 包）

本文件映射 `src/interclarify/` 与对应说明文档。阶段总览与验收证据见 [../../p0/README.md](../../p0/README.md)；P1 进展见 [../../p1/README.md](../../p1/README.md)。尚未实现的运行时模块（`asr/`、`layers/`、`arbitration/`、`playback/`、`task/`、`data/`、`evaluation/`）在实现时按同一约定补齐。

| 实现文件 | 说明文件 |
| --- | --- |
| `src/interclarify/__init__.py` | [index.md](index.md) |
| `src/interclarify/config.py` | [config.md](config.md) |
| `src/interclarify/manifest.py` | [manifest.md](manifest.md) |
| `src/interclarify/run.py` | [run.md](run.md) |
| `src/interclarify/duplex/__init__.py` | [duplex/__init__.md](duplex/__init__.md) |
| `src/interclarify/duplex/official_control.py` | [duplex/official_control.md](duplex/official_control.md) |
| `src/interclarify/duplex/official_server.py` | [duplex/official_server.md](duplex/official_server.md) |
| `src/interclarify/realtime/__init__.py` | [realtime/__init__.md](realtime/__init__.md) |
| `src/interclarify/realtime/clock.py` | [realtime/clock.md](realtime/clock.md) |
| `src/interclarify/realtime/playback.py` | [realtime/playback.md](realtime/playback.md) |
| `src/interclarify/realtime/scenarios.py` | [realtime/scenarios.md](realtime/scenarios.md) |
| `src/interclarify/realtime/client.py` | [realtime/client.md](realtime/client.md) |
| `scripts/check_env.py` | [../../scripts/check_env.md](../../scripts/check_env.md) |
| `scripts/check_audio_io.py` | [../../scripts/check_audio_io.md](../../scripts/check_audio_io.md) |
| `scripts/run_p0_smoke.py` | [../../scripts/run_p0_smoke.md](../../scripts/run_p0_smoke.md) |
| `scripts/run_p1_offline_sample.py` | [../../scripts/run_p1_offline_sample.md](../../scripts/run_p1_offline_sample.md) |
| `scripts/run_p1_2_live_link.py` | [../../scripts/run_p1_2_live_link.md](../../scripts/run_p1_2_live_link.md) |
| `scripts/prepare_p1_2_scenarios.py` | [../../scripts/prepare_p1_2_scenarios.md](../../scripts/prepare_p1_2_scenarios.md) |
| `scripts/remote/Dockerfile.p0` | [../../scripts/remote/Dockerfile.p0.md](../../scripts/remote/Dockerfile.p0.md) |
| `scripts/remote/setup_env.sh` | [../../scripts/remote/setup_env.md](../../scripts/remote/setup_env.md) |
| `scripts/remote/run_p0_node_job.sh` | [../../scripts/remote/run_p0_node_job.md](../../scripts/remote/run_p0_node_job.md) |
| `scripts/remote/submit_p0_job.sh` | [../../scripts/remote/submit_p0_job.md](../../scripts/remote/submit_p0_job.md) |
| `scripts/remote/sync_from_github.sh` | [../../scripts/remote/sync_from_github.md](../../scripts/remote/sync_from_github.md) |
| `scripts/remote/prepare_p1_assets.py` | [../../scripts/remote/prepare_p1_assets.md](../../scripts/remote/prepare_p1_assets.md) |
| `scripts/remote/run_p1_assets_node_job.sh` | [../../scripts/remote/run_p1_assets_node_job.md](../../scripts/remote/run_p1_assets_node_job.md) |
| `scripts/remote/submit_p1_assets_job.sh` | [../../scripts/remote/submit_p1_assets_job.md](../../scripts/remote/submit_p1_assets_job.md) |
| `scripts/remote/run_p1_offline_node_job.sh` | [../../scripts/remote/run_p1_offline_node_job.md](../../scripts/remote/run_p1_offline_node_job.md) |
| `scripts/remote/submit_p1_offline_job.sh` | [../../scripts/remote/submit_p1_offline_job.md](../../scripts/remote/submit_p1_offline_job.md) |
| `scripts/remote/run_p1_2_node_job.sh` | [../../scripts/remote/run_p1_2_node_job.md](../../scripts/remote/run_p1_2_node_job.md) |
| `scripts/remote/submit_p1_2_job.sh` | [../../scripts/remote/submit_p1_2_job.md](../../scripts/remote/submit_p1_2_job.md) |
| `scripts/remote/start_kyutai_services.sh` | [../../scripts/remote/start_kyutai_services.md](../../scripts/remote/start_kyutai_services.md) |
| `3rd-party/DuplexCascade/*` | [../../3rd-party/DuplexCascade.md](../../3rd-party/DuplexCascade.md) |
| `configs/*.yaml`、`configs/p1_2_scenarios.json` | [../../configs/README.md](../../configs/README.md) |
| `tests/test_p0_artifacts.py` | [../../tests/test_p0_artifacts.md](../../tests/test_p0_artifacts.md) |
| `tests/test_p1_assets.py` | [../../tests/test_p1_assets.md](../../tests/test_p1_assets.md) |
| `tests/test_p1_offline_control.py` | [../../tests/test_p1_offline_control.md](../../tests/test_p1_offline_control.md) |
| `tests/test_p1_2_realtime.py` | [../../tests/test_p1_2_realtime.md](../../tests/test_p1_2_realtime.md) |
