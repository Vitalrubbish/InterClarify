# 配置模板

统一配置层由 [src/interclarify/config.py](../../src/interclarify/config.py) 加载：先读 `base.yaml`，再叠加 profile，最后叠加运行时覆盖。

## `base.yaml`

- `run`：输出目录、随机种子、标签和会话标识；
- `paths`：仓库、数据、模型和产物根目录；
- `device`：CPU/GPU 与可见卡号；
- `audio`：16 kHz 单声道 float32、80 ms 块长、设备和 AEC 状态；
- `clock`：真实/虚拟时钟和 0.6 秒 micro-turn 初始值；
- `xtalk`：项目 fork、官方 upstream、固定提交、集群基础镜像和首轮候选模型组件；
- `logging`：日志级别与事件文件名。

`xtalk.source_root` 和模型 `revision` 当前为 `null`，表示尚未完成部署核验和运行冻结。候选为 Qwen3-ASR 1.7B + MOSS-TTS-Realtime（含 codec），沿用 Qwen3 回答模型与 XTurnix。P0 loader 只记录这些元数据，不启动或下载模型。

## `xtalk_round1.yaml`

独立的首轮模型准备配置，记录源码提交、模型 ID、conda 环境、分卡、端口、流式参数与系统附和关闭状态。详细字段见 [xtalk_round1.md](xtalk_round1.md)，执行入口见 [远端任务单](../jobs/xtalk_round1_baseline.md)。它不参与 `load_config` 的 profile 合并，也不能直接传给 `Xtalk.from_config`。ASR 接入缺口在配置中显式标记。

## profiles

- `local.yaml`：本地 GPU、真实音频设备、实时时钟；
- `replay.yaml`：CPU、无设备、虚拟时钟；
- `cluster.yaml`：集群 GPU、共享存储、实时时钟和 HF 镜像环境变量。

X-Talk 来源说明见 [xtalk_registry.md](../p0/xtalk_registry.md)。解析后的完整配置及 SHA-256 摘要随每次运行写入 manifest。
