# P0 路线重置与工程准备

本阶段对应 [engineering_implementation.md](../engineering_implementation.md) 第 4 节。2026-10-09 起，项目底座由“直接复现 DuplexCascade”改为“改造固定版本的 X-Talk”。P0 保留通用环境、配置、运行清单、事件日志和集群脚手架，删除旧路线专属实现与证据。

## 当前交付物

| 交付物 | 位置 | 说明 |
| --- | --- | --- |
| conda 环境 | [environment.yml](../../environment.yml)、[requirements.txt](../../requirements.txt) | Python 3.10 + 当前仓库通用依赖 |
| 依赖与底座登记 | [dependency_inventory.md](dependency_inventory.md)、[xtalk_registry.md](xtalk_registry.md) | X-Talk 来源、版本、许可证与待核验项 |
| 配置模板 | [configs/](../../configs/)、[docs/configs/README.md](../configs/README.md) | local / replay / cluster |
| 运行与清单 | [manifest.md](../src/interclarify/manifest.md)、[run.md](../src/interclarify/run.md) | 唯一运行目录与可复现信息 |
| 集群脚手架 | [scripts/remote/](../../scripts/remote/)、[任务单](../jobs/p0_environment_check.md) | P0 环境与冒烟检查 |
| 音频条件记录 | [audio_io_report.md](audio_io_report.md) | 当前 16 kHz 入口约定与设备限制 |

## 路线重置后的状态

- 已移除 DuplexCascade 第三方源码快照、官方权重/Kyutai 资产脚本、官方控制模型适配器、旧实时客户端、P1 测试和实验产物。
- `configs/base.yaml` 和 `manifest.json` 改为记录 X-Talk 来源。
- 当前仓库尚未导入或改造 X-Talk 源码；P1.0 必须先固定 checkout/fork、核验镜像与源码对应关系，再选择 ASR、TTS、LLM agent 和 turn detector。
- 旧 P0 GPU 与冒烟记录只能证明通用脚手架曾在集群运行，不能证明新的 X-Talk 基线已经完成。路线重置后需重新执行 P0 验收。

## 验收命令

```bash
conda env create -f environment.yml
conda run -n interclarify-dev python -m pip install -r requirements.txt
conda run -n interclarify-dev python scripts/check_env.py --require-gpu
conda run -n interclarify-dev python scripts/check_audio_io.py
conda run -n interclarify-dev python scripts/run_p0_smoke.py --profile replay
conda run -n interclarify-dev python -m pytest -q
```

集群验收继续使用 [p0_environment_check.md](../jobs/p0_environment_check.md) 和 [p0_job_runbook.md](remote/p0_job_runbook.md)。任何 X-Talk 模型或服务测试都应新建 P1 任务单，不能复用 P0 结果声称完成。

## 下一步

1. 核验 [xtalk_registry.md](xtalk_registry.md) 中的源码提交、镜像 digest 和许可证差异；
2. 建立 X-Talk 专用 conda 环境锁定或在现有环境中固定安装；
3. 跑通原生 X-Talk 最小链路；
4. 建立功能差距表和 FDB smoke；
5. 再开始 micro-turn、Layer 0/1、仲裁和播放边界改造。
