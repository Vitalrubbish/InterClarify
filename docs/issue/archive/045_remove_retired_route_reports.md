# Issue 045：删除 reports 下旧路线证据

状态：完成，归档。优先级：P2。日期：2026-10-20。依据：用户 2026-10-20 “再删除 reports 下的旧路线证据”。

## 范围

- 删除 `reports/layer1_training/issue005-probe-20261020/`：该目录记录 issue005 probe-only 训练路线的 32/100 条短跑、512 窗口资源测量及恢复结果，对应实现与配置已在 issue 044 删除。
- 保留 `reports/asr_selection`、`asr_text_surface`、`english_integration`、`full_chain`、`layer1_training` 其余当前证据，以及 `reports/maintenance` 三份清理/路径记录（用户确认保留）。
- `issue005-probe` 的 `full_train_index.json` 仅被 `tests/test_layer1_adaptation.py` 用作 512 窗口回归基线。该文件移为 `tests/fixtures/layer1_previous_full_train_index.json`，测试与同路径说明同步更新，不保留旧路线报告目录。
- `reports/layer1_training/issue006-preparation-20261020/plan.json` 与 `issue028-gate-scope-20261020/readiness.json` 中仍保留该文件的历史摘要键；它们是当时冻结输入的不可变记录，不参与当前校验，不做改写。

## 验证

- `tests.test_layer1_adaptation` 12 项通过（`ml-hw1` conda）。
- 当前跟踪文档相对链接扫描无悬空项。
- `reports/README.md` 删除记录补充 issue005 probe-only 报告。
