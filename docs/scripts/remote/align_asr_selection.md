# align_asr_selection.py

使用独立 Wav2Vec2 CTC 模型对冻结参考转写做离线强制对齐，不生成候选转写。无业务类。`ctc_path` 在含 blank 的展开标签序列上做 Viterbi 动态规划，禁止相邻重复标签跨越 blank；回溯后给每个字符分配声学帧。`align_sample` 将字符时间合并为规范化参考词的起止时间，保留标签平均对数概率。对齐时读取整段音频是离线评分行为，不进入在线模型。

生成的时间是模型估计而非人工标注，20ms 帧步长及识别模型自身误差会影响结果。失败记为 error，不删除样本。输出文件随 manifest revision、模型 revision 和文件摘要归档。
