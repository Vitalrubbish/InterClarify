# TTS 延迟优化远端任务单

日期：2026-10-17。状态：实验工具已准备，GPU 作业未提交。已通过交互 PTY 登录 JumpServer：使用现有 `js-hpc` SSH 配置和会话 key，等待菜单后输入 `p`，选择资产编号 `1`（`d6-hpc-debuggpu-001`，`10.24.19.254`），成功进入 `xuan.zhang` 的 shell。直接搜索 `guizhou` 返回“没有资产”；它是用户使用的集群名称，当前堡垒机资产名称不同。必须保持交互 stdin，不能在菜单出现前一次性管道发送多条命令。

已只读确认 `/usr/bin/vc`、共享 `miniconda3/bin/conda`、`xtalk-round1-moss`/`xtalk-round1-client` 环境及 `xtalk-round1/{models,moss-source,moss-service}` 目录存在。远端 `InterClarify` 在 main 且包含未跟踪的历史报告，后续使用独立 checkout，不覆盖现有目录。登录成功不代表 GPU 资源或性能验收已完成。

## 已验证的工具入口

本地 conda `paratalker-dev` 运行完整确定性测试与 WebSocket 协议夹具；`vllm-bench`（torch 2.11.0+cu130，仅 CPU）运行历史惩罚、完整码本对照与单图掩码检查。它与现役 torch 2.9.1 环境不同，不能替代真实 compile 验收。

生成非 FDB 文本集的入口为 `scripts/remote/tts_latency_benchmark.py --prepare-corpus <新JSONL路径>`。基准通过 `--corpus`、`--output`、`--reference`、`--url`、`--repeats` 和 `--server-trace` 接收显式配置。工具已用协议夹具验证，真实服务接入仍待确认。此处不提供未经固定 adapter 远端接入验证的完整提交命令。

## 登录恢复后的准备核对

1. 通过 GitHub 将本分支同步至独立、干净 checkout；禁止覆盖现役目录。保留实际提交、patch SHA256 及模型锁文件。
2. 核对历史共享根 `/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1` 下的模型、音色、MOSS 源码与 adapter。MOSS 源码必须为 `58b20a0d5fcc6766658d50967a90a9d890009a46`，adapter 必须为 `b3306b97f8a64c1a2f25b9803c070ff32ecff6b1`，二者 `git diff HEAD` 干净；不能假定历史目录仍然存在。
3. 核对实际 TTS conda prefix 与 `configs/xtalk_round1.yaml` 的 `xtalk-round1-moss` 同一环境；客户端使用独立 conda 环境。记录 Python、torch、transformers、flash-attn、模型 snapshot revision 和音色摘要。不升级现役环境。
4. 使用已有 `vc submit` 资源接口申请独占单张 `pdgpu-4090`，记录 GPU UUID、型号、驱动与峰值显存。登录节点只做文件/环境检查，GPU 测试只在分配节点执行。新的节点脚本和提交命令应在拿到真实路径并验证后再固化。

## 实验顺序与环境开关

| 阶段 | 设置与对照 | 必须保留的证据 |
| --- | --- | --- |
| 001 基线 | `XTALK_TTS_TRACE` 指向独立 JSONL；`XTALK_TTS_METRICS=1`；`XTALK_TTS_SEED=17`；batch=0、early=0 | 服务/客户端日志、配置与锁文件、每例 WAV/JSON、冷启动与 warmup 分开 |
| 002 批次 | 原路径与 batch=4 交错对照；仅该变量改变，再根据结果比较 2/6 | token 顺序、首音、batch 帧数、断流、盲试听、取消边界 |
| 003 开头编译 | 沿用 002 已通过配置，仅 `XTALK_TTS_EARLY_COMPILE=1` | 首 1/5/10/50 帧、逐帧 eager/compiled、Dynamo 编译/重编译日志与显存，真实采样数值差异 |
| 004 剩余瓶颈 | 重新读取完整阶段占比后才选一个分支 | 微基准、单变量文本流复测、音质；没有占比证据时保持等待 |

所有实验保留官方采样、音色、ASR/LLM 与话轮设置。每 arm 使用新目录与独立服务 trace，同一 35 条文本，整句/固定增量各 3 轮以上；两模式分别报告。每个 arm 冷启动、图编译、warmup 单列，正式测量前先检查第二个新会话是否热态，避免每会话重编译污染结果。各 arm 分时独占 GPU，交错次序需在节点驱动中固定。

先以工具协议夹具跑通的 `/tts/ws` 路径确认真实 adapter 收到显式 session ID、reference 和结束事件；再通过现有 X-Talk TTS 客户端对同一服务跑 smoke。未接通前不提交完整性能矩阵。若启用 profiler，另跑独立目录，不纳入性能验收。

## 缺项与停止条件

当前工具覆盖 command 队列、文本门槛、prefill/step、生成批次、实际 codec `_decode`、音色准备/缓存、PCM 入队和客户端接收。CPU span 可在同进程分解，CUDA event 单独采样。`gpu.slice` 的共享 backbone event 列表可能含上一轮尚未完成事件，不能据此精确分配逐响应 GPU 占比；未完成 event 保留 pending，不能当作零。

尚缺 socket 实际发送、X-Talk 播放器消费/取消日志、设备播放、GPU 重编译正式计数、首词对齐和人工波形核查。回放器只输出立即消费模拟和 RMS 起点，不代表真人听到时间。报告明确列出缺项；首包均值达标不能替代 p95、失败率、断流和音质。

取消验收须在真实 X-Talk 唯一播放链路覆盖生成中、codec 前后、PCM 已入缓冲及 EOS 附近；本地只验证未提交帧/PCM 的丢弃，不声称覆盖已入客户端缓冲或重复完成事件。组件通过后，冻结 ASR/LLM 做 FDB 小子集；Nemotron 尚未接通、X2 仅供诊断，沉默不得记为优化通过。

没有远端基线与盲试听前，不切换批次默认值，不宣布四项关闭，不启动 KV 复用、codec 编译或 backbone 编译。

## 2026-10-17 远端启动准备

已核对两份 MOSS checkout 的完整提交和 `git diff HEAD` 干净。模型锁记录 TTS revision `75682787d8e2fcc73faca37ba2931453ca9c4022`、codec revision `3cd226ba2947efa357ef453bcad111b6eafba782`，实际 snapshot 为共享 `paratalker-p0-models` 路径；音色为 `xtalk-round1/audio/reference.wav`。原 X-Talk 客户端来自 `xtalk-round1/xtalk@5f0d9959edf1026588246efbed827b078cbb114c`，仅用于组件 smoke，不能当作当前双工 fork 的集成验收。

本轮创建独立 `interclarify-tts-latency-20261017` checkout。新增[节点入口](scripts/remote/run_tts_latency_node_job.md)与[提交入口](scripts/remote/submit_tts_latency_job.md)，先在分配节点检查固定依赖、真实上游等价性，再通过 cold/warm 探针和原客户端 smoke 才运行正式基线。`--probe` 是显式接入检查模式，不替代正式数量门禁；新增理由是必须先确认真实 adapter 接通再投入完整矩阵。脚本按本文已核对路径构造，实际作业结果另记。
