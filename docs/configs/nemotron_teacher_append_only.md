# NTF-008冻结配置

`nemotron_teacher_append_only.json`记录教师文本纯追加、流式ASR、单块音频缓冲和同卡对照的源码、固定FDB30输入摘要、soft reset和资源边界。它是运行记录；实际默认值由教师前端和远端入口实现，复核时应逐项核对，不能只凭配置文件断言参数已生效。

相较NTF-007配置，新增`streaming_asr=true`、`rerecognition_after_complete=false`、`audio_buffer_blocks=4`、`asr_lookahead_steps=4`，配对改为`first_window_covering_main_block`。不更换模型权重、依赖、空增量规则、状态规则或音频回看／前瞻；不启用自生成文字或下游输出。字段不包含类或方法。
