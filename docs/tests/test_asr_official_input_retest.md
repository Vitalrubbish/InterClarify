# 官方输入复测契约测试

`tests/test_asr_official_input_retest.py` 的 `OfficialInputRetestTests` 使用字符 tokenizer 检查：前导/尾随空白不进入模型、空拍 no-voice、assistant IDs 原样保留、可选 BOS 只在开头出现。接话统计测试区分旧正文续写、控制 token 与边界后真正新正文，保留后续取消标记。另验证非固定官方源码会被拒绝，避免 oracle 来源漂移。

测试不加载模型或音频；远端 tokenizer/官方 AST 和真实 prompt IDs 审计提供实际权重条件下的验证。
