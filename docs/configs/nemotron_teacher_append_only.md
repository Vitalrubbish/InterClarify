# NTF-010冻结配置

`nemotron_teacher_append_only.json`记录词级规范分词、流式ASR、单块音频缓冲和同卡复测的源码、固定FDB30输入摘要、soft reset和资源边界。它是运行记录；实际默认值由教师前端和远端入口实现，复核时应逐项核对，不能只凭配置文件断言参数已生效。

相较NTF-008配置，`text_path`改为`word_level_canonical`，新增`canonical_tokenization=true`与`last_word_commit=space_or_empty_increment`。已完成词每步重新分词但只追加新后缀；最后一个未完成词不进入KV，词边界或空ASR增量后提交。不更换模型权重、依赖、空增量规则、状态规则或音频回看／前瞻；不启用自生成文字或下游输出。字段不包含类或方法。
