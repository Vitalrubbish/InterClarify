# 独立官方 Word 控制循环对照

`scripts/remote/compare_layer1_runtime.py` 只对照一套配置：真实 Kyutai Word、首非空词起拍、600ms、64-token 贪心。模型服务使用冻结 BF16 发布权重。移除 raw/超时残词发布和时钟组合，固定输出仅由 `--fixed-output-debug` 显式启用。

`load_word_cases` 读取 manifest 的五例样本，每例包含 `id`、`duration_seconds`、`word_events`（`type: Word`、`text`、实际 `arrival_seconds`）和来源摘要。检查事件种类、时序、结束时间及重复 ID，不从累计文本推造词边界。清单必须注明原始采集来源与摘要；结构校验不替代真实性核验。

`load_reference` 校验固定 server.py 摘要，执行原版 prompt、控制与解码 AST。参考侧直接使用普通 Word 列表，逐项 strip 后入队，保留官方每拍空格连接；集成侧将同批词按空格累计，送入现有 MicroTurnAssembler/RuntimeAdapter。首拍均为首非空 Word 后 600ms，各自生成完整历史。

`ReferenceKernel` 通过同一冻结 GPU 服务传递原始 IDs；`Tensor` 仅适配传输，`Tokenizer` 读取发布资产。内核预热及整拍提交观测避免冷启动和 EOS 未消费造成误判。`compare` 定位请求、prompt/生成 IDs、历史、控制、停止或正文的首次差异；无请求和请求错误不能记为通过。

运行命令为 `python scripts/remote/compare_layer1_runtime.py --official-source /path/server.py --tokenizer /path/tokenizer.json --model-url http://127.0.0.1:18806 --manifest /path/word_manifest.json --output /path/new-output`。可用 `--cases` 分片。输出保留输入、双方逐拍时间线、输入/源码摘要及必要样本覆盖；不以退出 0 替代资产与生命周期放行。
