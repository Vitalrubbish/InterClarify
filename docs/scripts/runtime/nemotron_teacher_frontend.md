# Nemotron 教师文字前端

对应`scripts/runtime/nemotron_teacher_frontend.py`。`TeacherCursor`核查原始字符只追加和解码步连续；`TeacherTextBuffer`按词级追加规范分词：已完成词组成稳定文本，每步对稳定文本做一次规范分词并只追加新后缀；最后一个未完成词只重编码用于审计，不进入KV。`official_control_text()`只调用冻结上游的去前导附和、去标点、归一化及中英文分隔函数，不清洗共享正文；工具文件摘要独立校验。

`process_step()`按训练顺序一次前向输入提示（仅首次）、前步有效状态、当前音频回看／主块／前瞻、本步已完成词和ASR结束符，不再用`argmax != EOS`门控是否注入。词后出现空格时立即提交；连续两个空ASR增量后提交最后一个词。若提交后ASR仍扩展该词，按退化后缀追加并记录`post_pause_extension`，不重放历史。空文本块保持为空，不插入占位词。状态规则、远场拒绝、空增量计数、`_reset_controller()`和真实音频覆盖配对保持约定。

词级追加合同：

- `committed_ids`只增长，同一位置写入KV后不改写；稳定文本的规范分词必须以已注入token为前缀，否则立即失败。
- 最后一个未完成词不进入KV；词边界或连续两个空ASR增量后提交，代价是尾词最多延后一个词边界／两次停顿。
- 若尾词提交后仍被ASR扩展，按退化后缀追加并记录`post_pause_extension`；该词不再是规范分词，但历史仍不可改写。
- `text_commit_index`等于累计注入token数，单调不减；`text_injected_tokens`为本步新后缀。
- `tail_replace_tokens`只统计尾部未完成词的重编码，范围不落在末尾立即报错。
- 不保存输入embedding账本、KV检查点，不调用`_revise()`，也没有累计序列、修订次数或重放token上限。

`reset_controller()`保持逻辑话轮KV、文字缓冲、游标和待反馈状态，只清理计数及发声标志。`close()`保留最后正文、未完成尾词诊断并释放KV，不强开门、不补静音、不回填EOF文字。

NTF-008起，complete／incomplete只 flush 已到达的教师文本并软 reset，不调用任何整轮ASR；`whole_turn_rerecognition_calls`恒为0。帧同时携带`service_state`、`service_completion_source`、`speech_detected`、`service_text`：直接complete且已有语音记为`model_complete`，无前置nonidle的complete以`no_speech`拒绝，教师路径不使用`wait_fallback`。

逐帧审计记录原始截止、控制全文、本步注入及累计token、尾部词和重编码次数、尾部token数、反馈状态、KV长度及时间。SharedContext只存当前原始正文及状态。真实KV支持长度查询时，每步核对缓存长度与本地账本一致。

正常前向只做一次，不再有独立的门控前向；因此教师文字注入不再等待模型判断。文本片段按增量编码，跨步词片段可能不与整词一次性分词完全一致，这是纯追加合同的明确代价；不得用历史重放修正。
