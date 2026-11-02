# X2 教师文本前端

对应`scripts/runtime/x2_teacher_frontend.py`，只调整闭合文本提交、来源和审计，完整复用`NemotronTeacherFrontend.process_step()`的音频、KV、状态调整与发布流程。

`ClosedTextBuffer`继承原规范分词缓冲：`update()`固定全部提交，不缓存尾词；`_extension()`一旦调用即失败，不容许退化拼接。规范分词的历史前缀检查仍执行。

`X2Context`将父类的开轮与发布来源翻译为`x2_streaming_asr`，在真实SharedContext校验之前改好来源；关闭沿用真实Context，状态与原子发布语义不变。这样不修改冻结Nemotron文件，也不会把X2文本误标成Nemotron。

`X2TeacherFrontend`继承原前端，替换缓冲与来源适配器。`process_step()`先要求两个80ms帧且没有未闭合组，再调用父类；验证累计注入token等于已闭合控制文本的规范分词，尾部审计为空／0／false。新增`empty_run_length`、实际状态差异`rule_applied`、本块RMS、组数、帧数和累计token摘要。空步频率不改变旧状态规则。完整组可含多个词，本实现不声称组内每个词均有独立边界。

NTF-017兼容更新：历史X2Context开轮显式固定publication_mode=legacy_frame，保留原教师实验与旧帧检查。当前独立双路X2默认joint，拒绝该旧入口，来源名称相同也不能在话轮内切换发布模式。本次不恢复历史教师路线。
