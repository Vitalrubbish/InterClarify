# Issue 044：仓库瘦身——旧路线实现、开关与过时文档引用

状态：完成，归档。优先级：P1。日期：2026-10-20。依据：用户 2026-10-20 瘦身指令及本轮逐项确认。

## 目标与范围

当前路线已冻结为 **Nemotron EN 0.6B/160ms + Kokoro 82M/af_heart + T2_R3_delayed_start（040/040b）**。本 issue 移除已被该路线彻底取代的实现、配置开关、pytest 测试与相应文档引用，不改变现路线行为，不重开组件选型，不修改训练数据或已提交作业。

issue 042 曾执行同一范围并提交为 `9af23ea`、`c3e5ad0`；用户随后在 issue 043 要求反向撤销。本轮经用户重新确认，按相同边界再次执行，并保留上一轮未提交的清理内容。

## 用户本轮确认的取舍

- X2/MOSS/TurnSense/round1-A4 旧组件栈整体删除。
- issue005 probe-only 训练路线删除。
- `duplex_a4_replay.py --native` 开关删除（无调用方）。
- 前一轮已暂存的过期工具删除继续生效。

## 明确保留的能力

| 保留项 | 理由 |
| --- | --- |
| `xtalk_link_check.py` 及其测试 | `duplex_a4_replay.py`（当前 FDB 驱动）继承其会话基类。 |
| `duplex_a4_replay.py` / `layer1_fdb.py` | 当前四配置 FDB 重放入口。 |
| `layer1_candidate.py` 的 T1/T2/T3 条件分支 | 旧 T2、T2_R2 是 040 重测的 `reference_conditions`。 |
| `run_layer1_fdb.sh` 的 `MODE=round1/round2_t2/delayed_t2` | 当前 040 重测仍需对比历史条件。 |
| `audit_layer1_dataset.py --baseline-dataset` | 040b 延迟启动协议直接校验新旧数据对照。 |
| `layer1_data.py` 的 `response_start_timing` | 用户明确暂不清理；旧 manifest 缺省复现同拍规则。 |
| `--alignment-probe` | 后续轮次仍可能运行资源探针。 |

## 工作单元

### A. 旧组件栈删除

- 实现：X2 ASR 服务与环境脚本、MOSS 吞吐补丁、TurnSense 服务、round1 模型准备、A4 节点/提交作业、A4 报告压缩器、round1 镜像及构建脚本。
- 配置：`configs/xtalk_duplex_x2_runtime.json`、`configs/xtalk_round1.yaml`。
- 测试：X2、MOSS、round1、A4 压缩器、A4 source manifest 相关用例；`test_duplex_a4_replay.py` 作为当前驱动测试保留。
- 同路径中文文档一并删除；`README.md`、`docs/asr_selection_report.md`、`docs/baseline_evidence.md`、`docs/scripts/remote/setup_fdb_scoring_env.md` 更新旧路线表述。
- `xtalk/` 为冻结上游仓库，不在本仓库瘦身范围。

### B. issue005 探针路线删除

- 删除 `configs/layer1_training.yaml`、`scripts/training/run_layer1_probe.py`、`scripts/remote/run_layer1_training.sh` 及同路径文档。
- `train_layer1.py`：移除 `issue005_probe_only` 分支与 32/100 smoke 子集读取；`--config` 改为必填；`--dialogues` 收敛为 1000。
- `build_layer1_dataset.py`：不再生成 `smoke_subsets.json`。
- `tests/test_layer1_training.py`：移除探针资源选择用例。

### C. 已归档任务的一次性工具

沿用上一轮已暂存删除：035 复测、017 零更新、001 系列资产/运行时对照、020 文本表面探针及对应 launcher、配置和同路径文档。保留其结果文档和历史证据。

### D. `--native` 开关删除

移除 `duplex_a4_replay.py` 的 argparse 开关、`serve_config` 的 `native` 参数及仅服务该路径的分支，同步更新驱动文档。

### E. 文档引用清理与收尾

- 修复指向已删除 `engineering_implementation.md`、`research_design.md`、`asr_cleanup.md` 的悬空引用。
- 修复 `environment.yml`、`pyproject.toml`、`requirements.txt` 中的过时文档路径。
- 全仓相对链接扫描，确保 docs 树与实现树一致。
- 清理 `src/` 下的空目录与缓存残留。

## 完成结果

- 删除旧组件栈、issue005 探针路线、`--native` 开关及已归档任务的一次性工具，共 98 份文件；同路径中文文档同步删除。
- `docs/scripts`、`docs/tests`、`docs/configs` 与 `scripts`、`tests`、`configs` 逐文件对应，无缺失或多余说明。
- 当前跟踪文档的相对链接扫描无悬空项；缺失的 `research_design.md`、`engineering_implementation.md`、`asr_cleanup.md` 引用已改写或移除。
- `paratalker-dev` 下除 `test_layer1_alignment.py`（本机无 torch）外的全部测试模块通过；`ml-hw1` 下 `test_layer1_alignment`、`test_layer1_training`、`test_layer1_loading` 共 23 项通过。远端 GPU 专属用例保持原样 skip。
- 保留 `xtalk_link_check.py`、`duplex_a4_replay.py`、`layer1_fdb.py`、T1/T2/T3 参考条件、`--alignment-probe` 与延迟启动数据协议。
- 未修改 040b 已运行作业的冻结源码、数据或输出。
