# FDB持续等待与ASR词识别诊断

`scripts/training/diagnose_layer1_fdb.py`离线读取034回收的100份真实测试摘要、最终ASR/模型可见前缀、控制事件、原始参考标注及健康记录，不加载模型、不发送请求、不进行内容质量计分。

`words`统一大小写、Unicode撇号和空白，去除标点与PAUSE/TURN-TAKING等非语音标记；保留填充词、词内撇号和词本身，不自动扩写数字或缩写。`reference_text`优先读取原始transcription.json，合成插话仅连接其context/interrupt字段；没有完整转写的Candor turn-taking保留null，不拿边界标记当参考。

`edit_counts`用标准Levenshtein最短对齐计算替换/删除/插入，输出语料级WER和逐例错误；与官方FDB输出音频对齐、内容judge和人工听写有区别。原始标注也可能有误，分数只表示与该参考的词级差异，不能证明某个争议词实际发音。

`analyze`分别按配置/子集统计实际语音输出、纯talking、稳定最终前缀后的控制，并对比四次ASR最终结果是否完全一致。插话样本区分初始回答与插话后的新响应，按response ID对应的播放代理起点及原始输入窗口核对；不把旧音频或诊断尾窗响应计为成功换题。终末句读单独记字段，不视为词识别错误。输出逐例JSON、CSV和summary，缺失参考/指标保留null。

脚本只支持本轮已冻结100会话观测，检查每配置25唯一输入、健康条件和退出码；不同配置的ASR发射时间并不保证逐拍相同，不将其忽略。分析结果用于定位ASR与模型问题，不能冒充官方TOR或独立泛化验收。
