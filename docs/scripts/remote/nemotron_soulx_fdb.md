# FDB 三类 Nemotron＋SoulX 抽样入口

对应 `scripts/remote/nemotron_soulx_fdb.py`，遵循[本轮计划](../../dev/SoulX-Duplug/fdb_sample_review.md)。无新增模型类；复用 `nemotron_soulx_probe.run_case()` 和已有前端，不改变推理逻辑。

`freeze()` 在数据目录的固定排序上按种子抽取30条，冻结 input.wav、标签及可用参考文字的摘要、时长和原始标注；检查数量、时间范围与1200秒总音频上限。只读取抽中样本的小文件，不复制音频。

`load_controller()` 复用摘要锁定的既有 SoulX 加载器，将 SenseVoice 类临时替换为拒绝识别的空壳；不加载第二个 ASR。`run()` 逐条核对摘要、读取并按既有增益标定音频，每条 reset 后复用实时回放函数；失败记录在结果中，保留部分轨迹，CUDA OOM 后终止。原生 EOF 排空不倒填在线文字。

`analyze_case()` 解析原始事件，输出包含原始预测、最终 token、规则调整、Context 全文、实际消费全文与 generation 控制文本的逐帧 CSV；核查消费版本、控制引用和因果音频上界。接话与打断结束以官方时间边界比较 complete，停顿以官方区间检查 complete 和 incomplete。`first_nonidle` 与 `first_nonidle_transition` 分开记录。所有判断同时保留处理截止和音频观察截止，不将模型输入的前瞻隐藏。

`word_errors()` 仅做大小写、标点归一化后的词级编辑距离，不做数字语义转换；报告 S／D／I、参考词数和 WER，不能用可读性代替准确率。停顿读取 transcription.json；打断用 interrupt.json 的 context＋interrupt 作为整段参考，另记录两段参考和在线结果；接话缺参考不计算 WER。

`analyze()` 可在本地已有 conda 对下载结果复查，不加载模型；保存30条独立摘要、逐帧轨迹及分组计数。标注、ASR参考只参与 freeze 和事后分析，不进入 `run_case()`。
