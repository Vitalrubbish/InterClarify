# Issue 049：删除旧训练/FDB 设计及开关

状态：完成，归档。优先级：P1。日期：2026-10-21。依据：用户要求在最终阶段关闭后继续删除旧设计及其开关。

## 保留路线

只保留最终 `T2_R3_delayed_start`：固定延迟启动数据、控制加权 CE、1,235 步/2,469 序列、最终 epoch checkpoint、单一 FDB 子集入口和干净进程候选重载。历史 006/036/037 结果仍保存在报告与固定 Git 提交中。

## 删除内容

- 036 对齐探针：`--alignment-probe`、`run_layer1_alignment.py run`、对齐协议/配置、probe 候选分支及对应用例。
- 旧时序兼容：`response_start_timing` 的 `same_user_chunk` 分支与默认值、`audit_layer1_dataset.py --baseline-dataset` 新旧数据对照。
- 旧训练/FDB 条件：006 T1/T2/T3、037 T2_R2、`round1`/`round2_t2` 模式及旧候选 purpose 分支，只保留 T2_R3。
- 无入口引用的离线分析脚本：`analyze_layer1_loss.py`、`diagnose_layer1_fdb.py`、`summarize_layer1_fdb.py`。
- 006 四配置训练配置、036 对齐配置/协议、017 加载测试依赖配置及其同路径文档。
- `tests/test_layer1_adaptation.py` 与 `tests/test_layer1_alignment.py`；加权 loss/候选重载用例迁入 `tests/test_layer1_weighted_loss.py`。

## 实现结果

- `train_layer1.py` 只接受 `issue040_delayed_start`、T2、1,000 条对话；移除 index、probe、普通 CE 和 006/036 分支。
- `prepare_layer1_adaptation.py` 只保留父协议门禁、T2 索引和延迟配置校验；期望配置在模块内冻结。
- `layer1_candidate.py` 只接受 T2_R3 最终候选；`run_layer1_alignment.py` 只保留干净进程重载验证。
- `layer1_data.py` 固定延迟启动时序；`audit_layer1_dataset.py` 固定时序审计，不再接受旧基线。
- `run_layer1_fdb.sh` 固定 T2_R3，删除模式与四条件选择。

## 验证

- `ml-hw1`：加权 loss、延迟训练、数据管线、训练契约、候选共 51 项通过；torch 相关加载/训练 18 项通过。
- `paratalker-dev`：除需 torch 的模块外全部测试模块通过。
- `docs/scripts`、`docs/tests`、`docs/configs` 与实现逐文件对应；相对链接扫描无悬空项。
