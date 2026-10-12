# InterClarify

InterClarify 研究全双工语音代理在**用户话轮内**主动澄清的时机与措辞：当持续到达的语音前缀存在会改变任务结果的解释分歧时，系统应继续听、趁合适的接话机会简短提问，还是直接回答；用户回应后如何把答案并回原任务。研究范围见 [docs/research_design.md](docs/research_design.md)，工程阶段、门禁与模块边界见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

参考底座为独立维护的 [Vitalrubbish/xtalk](https://github.com/Vitalrubbish/xtalk) fork。第一阶段先跑通并冻结一套原生组件组合，再补齐 DuplexCascade 无 System Backchannel 版本的 micro-turn、Layer 1、提前回答、持续监听、用户附和识别和打断停播；当前移除 Layer 0，底座稳定后再接入 InterClarify Layer 2。InterClarify 不跟踪 X-Talk 源码或子模块，只记录实验使用的 fork 提交。

**当前状态：A2/A3 已实现于 X-Talk dev 提交 a06dd57，官方权重远端运行时冒烟通过。** A1 提交为 9c131ed；本次改造用源码摘要 17fd22d55cc7 标识。真实模型完成 12 个 micro-turn、协议错误 0；完整 ASR/MOSS 音频、FDB 与 A4 验收仍待完成，Layer 2 尚未接入。

## 当前基础设施

| 交付物 | 位置 |
| --- | --- |
| 固定 conda 环境 | [environment.yml](environment.yml) + [requirements.txt](requirements.txt) |
| 当前 X-Talk 组件与复测基线 | [docs/xtalk_baseline_stack.md](docs/xtalk_baseline_stack.md) |
| 三类配置模板 | [configs/](configs/)（local / replay / cluster） |
| 实验清单格式 | `manifest.json` / `resolved_config.yaml` / `events.jsonl`，见 [docs/src/interclarify/run.md](docs/src/interclarify/run.md) |
| 当前远端复测入口 | [scripts/remote/submit_xtalk_round1_job.sh](scripts/remote/submit_xtalk_round1_job.sh) 与 [docs/scripts/remote/submit_xtalk_round1_job.md](docs/scripts/remote/submit_xtalk_round1_job.md) |

## 本地环境与验收

```bash
conda env create -f environment.yml
conda run -n interclarify-dev python -m pip install -r requirements.txt

# 环境自检（无 GPU 时可省略 --require-gpu）
conda run -n interclarify-dev python scripts/check_env.py --require-gpu
# 音频设备探测（headless 机器报告 NO_DEVICES 属预期）
conda run -n interclarify-dev python scripts/check_audio_io.py

# 确定性离线冒烟：同一输入与配置应产生结构一致的日志
conda run -n interclarify-dev python scripts/run_p0_smoke.py --profile replay

# 单元测试
conda run -n interclarify-dev python -m pytest -q
```

当前模型链路复测使用 `bash scripts/remote/submit_xtalk_round1_job.sh link` 提交；它在远端 conda 环境中运行顺序两轮和插话续答检查。完整判据见 [docs/scripts/remote/xtalk_link_check.md](docs/scripts/remote/xtalk_link_check.md)。

## 文档索引

- 实现文档（按源码树镜像）：[docs/src/interclarify/](docs/src/interclarify/)、[docs/scripts/](docs/scripts/)、[docs/configs/](docs/configs/)
- 研究设计：[docs/research_design.md](docs/research_design.md)；工程方案：[docs/engineering_implementation.md](docs/engineering_implementation.md)
- X-Talk 具体改造方案：[docs/xtalk_modification_plan.md](docs/xtalk_modification_plan.md)
- 当前组件、复测证据与冻结边界：[docs/xtalk_baseline_stack.md](docs/xtalk_baseline_stack.md)
- 首轮模型配置：[configs/xtalk_round1.yaml](configs/xtalk_round1.yaml)；运行配置：[configs/xtalk_round1_runtime.json](configs/xtalk_round1_runtime.json)
- 下一阶段方案：[docs/xtalk_modification_plan.md](docs/xtalk_modification_plan.md)（P1 控制层改造）

实现行为若与文档不一致，先更新文档并说明原因，再改代码。

阶段 A 当前已在本地完成 A2/A3 micro-turn 与官方 token 在线执行，官方权重验证和源码同步记录见 [远端任务单](docs/xtalk_duplex_remote_task.md)。配置入口为 [xtalk_duplex_runtime.json](configs/xtalk_duplex_runtime.json)，原生连接基线保留作对照。
