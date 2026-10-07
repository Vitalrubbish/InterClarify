# InterClarify

InterClarify 研究全双工语音代理在**用户话轮内**主动澄清的时机与措辞：当持续到达的语音前缀存在会改变任务结果的解释分歧时，系统应继续听、趁合适的接话机会简短提问，还是直接回答；用户回应后如何把答案并回原任务。研究范围见 [docs/research_design.md](docs/research_design.md)，工程阶段、门禁与模块边界见 [docs/engineering_implementation.md](docs/engineering_implementation.md)。

参考底座为 [DuplexCascade](https://github.com/sbintuitions/DuplexCascade)（流式 ASR–LLM–TTS + micro-turn 控制）。**当前完成 P0（工程准备）**；P1 起才复现官方推理链路，本仓库暂不包含 Layer 0/1/2 运行时。

## P0 交付物

| 交付物 | 位置 |
| --- | --- |
| 固定 conda 环境 | [environment.yml](environment.yml) + [requirements.txt](requirements.txt) |
| 依赖与模型清单 | [docs/p0/dependency_inventory.md](docs/p0/dependency_inventory.md)、[docs/p0/duplexcascade_registry.md](docs/p0/duplexcascade_registry.md) |
| 三类配置模板 | [configs/](configs/)（local / replay / cluster） |
| 实验清单格式 | `manifest.json` / `resolved_config.yaml` / `events.jsonl`，见 [docs/p0/README.md](docs/p0/README.md) |
| 集群镜像与任务脚本 | [scripts/remote/](scripts/remote/)、任务单 [docs/jobs/p0_environment_check.md](docs/jobs/p0_environment_check.md) |

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

集群验收使用 [scripts/remote/submit_p0_job.sh](scripts/remote/submit_p0_job.sh) 提交，证据写入共享存储，执行手册见 [docs/p0/remote/p0_job_runbook.md](docs/p0/remote/p0_job_runbook.md)。

## 文档索引

- P0 阶段总览与验收：[docs/p0/README.md](docs/p0/README.md)
- 实现文档（按源码树镜像）：[docs/src/interclarify/](docs/src/interclarify/)、[docs/scripts/](docs/scripts/)、[docs/configs/](docs/configs/)
- 研究设计：[docs/research_design.md](docs/research_design.md)；工程方案：[docs/engineering_implementation.md](docs/engineering_implementation.md)

实现行为若与文档不一致，先更新文档并说明原因，再改代码。
