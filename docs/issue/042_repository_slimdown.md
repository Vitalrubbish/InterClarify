# Issue 042：仓库瘦身——移除旧路线实现、开关与过时文档引用

状态：进行中。优先级：P1。依据：用户 2026-10-20 瘦身指令及逐项确认。

## 目标与范围

当前路线已冻结为 **Nemotron EN 0.6B/160ms + Kokoro 82M/af_heart + T2_R3_delayed_start（040/040b）**。本 issue 移除已被该路线彻底取代的实现、配置开关、pytest 测试与相应文档引用；不改变任何现路线行为，不重开组件选型，不修改训练数据或已提交作业。

## 用户已确认的取舍

- X2 诊断路线彻底删除（取代 asr_selection_report 中"保留作诊断"的旧决定）。
- 旧 round1/A4 组件栈（MOSS 补丁、TurnSense、run_xtalk_round1、A4 作业、Docker 镜像、xtalk_link_check 等）整体删除。
- issue005 探针路线（`purpose: issue005_probe_only`）删除。
- `--alignment-probe` 探针路径**保留**（未来轮次仍可能跑资源探针）。
- 已归档 issue 的一次性工具与 launcher 全部删除。
- 首轮 round1（issue006）训练验证与 `layer1_candidate.py` 的 T1/T2/T3 服务分支**保留**：旧 T2、T2_R2 是 040 重测的 `reference_conditions`。

## 明确保留的开关（已核实依赖）

| 开关 | 保留理由 |
| --- | --- |
| `response_start_timing`（`same_user_chunk`/`next_no_voice`，layer1_data.py） | 用户明确暂不清理；旧 manifest 缺省复现同拍规则 |
| `run_layer1_fdb.sh` 的 `MODE=round1/round2_t2` | 040 重测需对比旧 T2 与第二轮 T2 |
| `audit_layer1_dataset.py --baseline-dataset` 新旧对比 | `validate_delayed_config` 直接校验 `audit['baseline_comparison']`，属 040b 协议身份 |
| `duplex_a4_replay.py --native` | 现驱动恒 `native=False`，仅历史对比；待 040 重测方案确定后另行处理 |
| `check_layer1_zero_update.py --worker` | 随 017 工具删除（见工作单元 C） |

## 工作单元

### A. 旧组件栈删除（X2 + MOSS + TurnSense + round1/A4）

- 实现：`scripts/remote/x2_asr_service.py`、`setup_x2_asr_env.sh`、`moss_tts_patch.py`、`turnsense/`、`run_xtalk_round1.py`、`run_xtalk_duplex_a4_node_job.sh`、`submit_xtalk_duplex_a4_job.sh`、`compact_a4_report.py`、`xtalk_link_check.py`、`Dockerfile.round1(.overlay)`、`build_xtalk_lean_base.sh`、`build_xtalk_round1_image.sh`
- 配置：`configs/xtalk_duplex_x2_runtime.json`、`configs/xtalk_round1.yaml`
- 测试：`test_x2_asr_service.py`、`test_moss_tts_patch.py`、`test_xtalk_round1.py`、`test_compact_a4_report.py`、`test_xtalk_link_check.py`
- 同路径中文文档一并删除；`docs/asr_selection_report.md`、`docs/baseline_evidence.md`、`README.md` 中"保留作诊断/历史依赖"表述同步更新。
- `xtalk/` 为冻结上游仓库，其内部 X2/MOSS/TurnSense 客户端不属本仓库瘦身范围。

### B. issue005 探针路线删除

- `train_layer1.py`：移除 `issue005_probe_only` 分支、32/100 smoke 子集读取，`--config` 改为必填（原默认 `configs/layer1_training.yaml` 删除），`--dialogues` 收敛为 1000。
- `build_layer1_dataset.py`：不再生成 `smoke_subsets.json`（无消费方）。
- 删除：`configs/layer1_training.yaml`、`scripts/training/run_layer1_probe.py`、`scripts/remote/run_layer1_training.sh` 及文档。
- `tests/test_layer1_training.py` 同步移除 `run_layer1_probe` 依赖用例；其余监督/恢复用例保留。
- 既有数据集（r5、issue040-delayed-start-data）中已存在的 `smoke_subsets.json` 只是冗余文件，不影响任何校验，不重算。

### C. 已归档 issue 一次性工具删除

- 035 复测：`retest_asr_official_input.py`、`run_asr_official_input_retest.sh`、`test_asr_official_input_retest.py`（结果文档 `docs/asr_official_input_retest.md` 保留为证据）
- 017 零更新：`check_layer1_zero_update.py`、`configs/layer1_zero_update.yaml`、`run_layer1_zero_update.sh`
- 001 系：`compare_layer1_runtime.py`、`capture_kyutai_words.py`、`inventory_layer1_assets.py`（`reports/.../inventory_summary.json` 产物仍被现行 configs 的 `verified_inventory` 引用，保留产物）
- 020/早期：`probe_asr_text_surface.py`、`duplex_runtime_smoke.py`、`probe_layer1_data.py`
- launcher：`run_layer1_training.sh`(B)、`run_layer1_zero_update.sh`、`run_layer1_runtime_comparison.sh`、`run_layer1_2048_stability.sh`、`run_layer1_round1.sh`、`run_layer1_adaptation.sh`、`run_layer1_alignment.sh`、`run_layer1_t2_round2.sh`、`run_issue004_alignment_rebuild.sh`、`run_layer1_data.sh`、`run_layer1_data_probe.sh`
- 保留：`run_layer1_fdb.sh`、`run_layer1_delayed_training.sh`、`run_issue040_data_rebuild.sh`、`run_full_chain_smoke.sh`、英文组件环境/作业脚本、FDB 评分脚本、`run_layer1_alignment.py`（verify 子命令为 037/040b 候选验证入口）。

### D. 文档引用清理与收尾

- 修复指向已删除 `engineering_implementation.md`/`research_design.md`/`asr_cleanup.md` 的悬空引用：`AGENTS.md`、`README.md`、`docs/issue/README.md`、`docs/asr_selection_report.md`、`docs/scripts/check_env.md`、`docs/scripts/check_audio_io.md`、`requirements.txt` 头注；修正 `environment.yml` 指向不存在的 `docs/p0/dependency_inventory.md`。
- 全仓相对链接扫描，确保 docs 树与实现树一致。
- 清理 `src/` 下仅剩的旧实现 `__pycache__` 残留。

## 完成条件

- 上述文件删除且同路径文档同步；无悬空相对链接。
- 本地 pytest 全绿（GPU/远端专属用例按原样 skip）。
- 不改动 040b 在跑作业的冻结源码引用（远端作业固定在提交 `91b7eb2`，不受仓库后续演进影响）。
- 每个工作单元独立提交；完成后本 issue 归档。
