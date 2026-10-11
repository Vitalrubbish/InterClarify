# 实现文档索引（interclarify 包）

本文件映射当前实现与对应说明。X-Talk 运行时及 Layer 1/2、仲裁和播放桥接仍在独立 fork 或后续阶段实现；Layer 0 不属于当前范围。新增实现时必须同步建立对应说明。

| 实现文件 | 说明文件 |
| --- | --- |
| `src/interclarify/__init__.py` | [index.md](index.md) |
| `src/interclarify/config.py` | [config.md](config.md) |
| `src/interclarify/manifest.py` | [manifest.md](manifest.md) |
| `src/interclarify/run.py` | [run.md](run.md) |
| `scripts/check_env.py` | [../../scripts/check_env.md](../../scripts/check_env.md) |
| `scripts/check_audio_io.py` | [../../scripts/check_audio_io.md](../../scripts/check_audio_io.md) |
| `scripts/run_p0_smoke.py` | [../../scripts/run_p0_smoke.md](../../scripts/run_p0_smoke.md) |
| `scripts/remote/setup_env.sh` | [../../scripts/remote/setup_env.md](../../scripts/remote/setup_env.md) |
| `scripts/remote/sync_from_github.sh` | [../../scripts/remote/sync_from_github.md](../../scripts/remote/sync_from_github.md) |
| `scripts/remote/run_xtalk_round1.py` | [../../scripts/remote/run_xtalk_round1.md](../../scripts/remote/run_xtalk_round1.md) |
| `scripts/remote/Dockerfile.round1` | [../../scripts/remote/Dockerfile.round1.md](../../scripts/remote/Dockerfile.round1.md) |
| `scripts/remote/build_xtalk_round1_image.sh` | [../../scripts/remote/build_xtalk_round1_image.md](../../scripts/remote/build_xtalk_round1_image.md) |
| `scripts/remote/build_xtalk_lean_base.sh` | [../../scripts/remote/build_xtalk_lean_base.md](../../scripts/remote/build_xtalk_lean_base.md) |
| `scripts/remote/submit_xtalk_round1_job.sh` | [../../scripts/remote/submit_xtalk_round1_job.md](../../scripts/remote/submit_xtalk_round1_job.md) |
| `scripts/remote/run_xtalk_round1_node_job.sh` | [../../scripts/remote/run_xtalk_round1_node_job.md](../../scripts/remote/run_xtalk_round1_node_job.md) |
| `scripts/remote/qwen3_asr_service.py` | [../../scripts/remote/qwen3_asr_service.md](../../scripts/remote/qwen3_asr_service.md) |
| `scripts/remote/xtalk_link_check.py` | [../../scripts/remote/xtalk_link_check.md](../../scripts/remote/xtalk_link_check.md) |
| `scripts/remote/turnsense/` | [../../scripts/remote/turnsense/README.md](../../scripts/remote/turnsense/README.md) |
| `configs/*.yaml` | [../../configs/README.md](../../configs/README.md) |
| `configs/xtalk_round1.yaml` | [../../configs/xtalk_round1.md](../../configs/xtalk_round1.md) |
| `tests/test_p0_artifacts.py` | [../../tests/test_p0_artifacts.md](../../tests/test_p0_artifacts.md) |
| `tests/test_xtalk_round1.py` | [../../tests/test_xtalk_round1.md](../../tests/test_xtalk_round1.md) |
| `tests/test_xtalk_link_check.py` | [../../tests/test_xtalk_link_check.md](../../tests/test_xtalk_link_check.md) |
