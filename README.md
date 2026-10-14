# InterClarify

InterClarify 研究全双工语音代理在**用户话轮内**主动澄清的时机与措辞：当持续到达的语音前缀存在会改变任务结果的解释分歧时，系统应继续听、趁合适的接话机会简短提问，还是直接回答；用户回应后如何把答案并回原任务。研究范围见 [docs/research_design.md](docs/research_design.md)，工程阶段、门禁与模块边界见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

参考底座为独立维护的 [Vitalrubbish/xtalk](https://github.com/Vitalrubbish/xtalk) fork。第一阶段先跑通并冻结一套原生组件组合，再补齐 DuplexCascade 无 System Backchannel 版本的 micro-turn、Layer 1、提前回答、持续监听、用户附和识别和打断停播；当前移除 Layer 0，底座稳定后再接入 InterClarify Layer 2。InterClarify 不跟踪 X-Talk 源码或子模块，只记录实验使用的 fork 提交。

**当前状态：阶段 A 全双工运行时已实现并完成验收。** A1–A3 与官方 DuplexCascade 权重运行时对齐（X-Talk fork `2f595f3`），A4 在远端 3 卡作业上跑通回放场景与 FDB 四轴；ASR append-only 输入契约（方案 B）复检后 `user_interruption` 的 `average_rating` 由 0.6 升到 2.25，剩余瓶颈是 MOSS-TTS 的合成产量（0.2–0.5 倍实时），已实现运行时补丁 `moss_tts_patch.py`（T1 local transformer 编译后端 / T2 采样头）。Layer 2 尚未接入。

## 当前基础设施

| 交付物 | 位置 |
| --- | --- |
| X-Talk fork 与复测基线 | [docs/xtalk_baseline_stack.md](docs/xtalk_baseline_stack.md) |
| 原生组件配置 | [configs/xtalk_round1.yaml](configs/xtalk_round1.yaml)、[configs/xtalk_round1_runtime.json](configs/xtalk_round1_runtime.json) |
| 阶段 A 全双工配置 | [configs/xtalk_duplex_runtime.json](configs/xtalk_duplex_runtime.json) |
| 原生链路远端复测入口 | [scripts/remote/submit_xtalk_round1_job.sh](scripts/remote/submit_xtalk_round1_job.sh) → [docs/scripts/remote/xtalk_link_check.md](docs/scripts/remote/xtalk_link_check.md) |
| 阶段 A 全双工验收 | 任务单 [docs/xtalk_a4_remote_acceptance.md](docs/xtalk_a4_remote_acceptance.md)、入口 [scripts/remote/submit_xtalk_duplex_a4_job.sh](scripts/remote/submit_xtalk_duplex_a4_job.sh)、报告 [reports/duplex_acceptance/](reports/duplex_acceptance/) |
| TTS 吞吐补丁与测量 | [docs/scripts/remote/moss_tts_patch.md](docs/scripts/remote/moss_tts_patch.md)、[docs/scripts/remote/run_tts_throughput_ab_node_job.md](docs/scripts/remote/run_tts_throughput_ab_node_job.md) |
| 集群镜像与 conda 环境 | [scripts/remote/Dockerfile.round1](scripts/remote/Dockerfile.round1)、[scripts/remote/setup_env.sh](scripts/remote/setup_env.sh)、[environment.yml](environment.yml)、[requirements.txt](requirements.txt) |

## 本地与远端运行

```bash
# 建环境（本地用 conda，集群节点同样用 conda）
conda env create -f environment.yml
conda run -n interclarify-dev python -m pip install -r requirements.txt

# 环境自检（无 GPU 时可省略 --require-gpu）；headless 机器报告 NO_DEVICES 属预期
conda run -n interclarify-dev python scripts/check_env.py --require-gpu
conda run -n interclarify-dev python scripts/check_audio_io.py

# 单元测试（需要 xtalk fork 源码与客户端依赖；moss_tts_patch 的用例只在 TTS 环境实跑）
PYTHONPATH=xtalk/src conda run -n xtalk-round1-client python -m unittest \
  tests.test_qwen3_asr_service tests.test_xtalk_round1 tests.test_duplex_a4_replay \
  tests.test_duplex_model_service tests.test_xtalk_link_check tests.test_moss_tts_patch
```

远端复测使用 `bash scripts/remote/submit_xtalk_round1_job.sh link`（原生组件组合）或 `bash scripts/remote/submit_xtalk_duplex_a4_job.sh`（阶段 A 全双工验收）；完整判据见各自的任务单。

## 文档索引

- 研究设计：[docs/research_design.md](docs/research_design.md)；工程方案：[docs/engineering_implementation.md](docs/engineering_implementation.md)
- 阶段 A 全双工验收任务单：[docs/xtalk_a4_remote_acceptance.md](docs/xtalk_a4_remote_acceptance.md)；证据：[reports/duplex_acceptance/](reports/duplex_acceptance/)
- X-Talk 具体改造方案：[docs/xtalk_modification_plan.md](docs/xtalk_modification_plan.md)；当前组件与冻结边界：[docs/xtalk_baseline_stack.md](docs/xtalk_baseline_stack.md)
- 脚本与配置说明：[docs/scripts/](docs/scripts/)、[docs/configs/](docs/configs/)；单测说明：[docs/tests/](docs/tests/)

实现行为若与文档不一致，先更新文档并说明原因，再改代码。

阶段 A 的门禁与证据链：A1–A3 实现于 X-Talk fork（历史提交 `9c131ed` / `2f8a433`，当前对齐到 `2f595f3`），A4 由 3 卡作业完成回放场景、FDB 四轴推理与官方 judge 复检；`reports/duplex_acceptance/20261014T033949Z/` 是当前保留的唯一一轮验收证据。原生连接基线（`20261011T054900Z`）作为对照保留在 [基线栈文档](docs/xtalk_baseline_stack.md) 里。

2026-10-14 做过一次仓库清理：只保留**原生 X-Talk 复现**与**阶段 A 最终实现**，一次性诊断作业（标记探针、逐拍 trace、ASR before/after 对比、pre-A4 运行时冒烟）及其产物已移除，结论与数字保留在 [A4 任务单](docs/xtalk_a4_remote_acceptance.md) §9 与 §13。
