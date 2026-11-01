# NTF-007冻结配置

`nemotron_teacher_append_only.json`记录本轮教师文本纯追加改造的源码、固定FDB30输入摘要、soft reset和资源边界。它是运行记录；实际默认值由教师前端和远端入口实现，复核时应逐项核对，不能只凭配置文件断言参数已生效。

相较NTF-004配置，删除`sequence_tokens`、`max_rebuilds`、`max_replay_tokens`三项缓存上限，`control_mode`改为`official_format_append_only_teacher`，新增`text_path=append_only`。不更换模型权重、依赖、空增量规则、状态规则或真实音频覆盖配对；不启用自生成文字或下游输出。字段不包含类或方法。
