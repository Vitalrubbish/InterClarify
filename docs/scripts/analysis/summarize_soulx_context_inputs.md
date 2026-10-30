# SoulX 逐样本输入汇总

`scripts/analysis/summarize_soulx_context_inputs.py` 读取已完成的真实回放，输出逐样本草稿、整段覆盖前后输入及全部在线 Context 正文变化。只做离线整理，不调用模型，不修改 Context 或原始证据，无额外类。

`summarize_case()` 按来源日志顺序捕获 `apply_deltas` 的最新全文、覆盖前已发布正文和每次整段识别。整段结果必须在后续联合帧中出现，并与实际 snapshots 的正文序列一致；关闭正文也需吻合，否则失败。草稿可能在同一步被覆盖，不能直接解释成下游已经读到的输入。

`render()` 生成中文逐样本表与完整正文变化表。整段识别没有发生时明确记录；排空结果与在线发布分别标记。`main()` 接收 `--replay` 原始目录及 `--output` 输出目录，生成 `inputs.json` 与 `sample_inputs.md`。文本保留识别原文，不修订语法或标点。

本地使用 `interclarify-dev` conda 运行，无需 GPU。验证采用实际六视图证据的来源、快照和关闭正文交叉核对，不增加模型替身测试。
