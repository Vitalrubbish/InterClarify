# 五例原生 Kyutai Word 采集

`scripts/remote/capture_kyutai_words.py` 仅用于 001 的缺失输入补采，不是产品 ASR 服务；无类。`capture` 将已冻结音频重采样为 24kHz，以 80ms 实时节拍发送官方 Audio 消息，独立接收并保存原始 Word/Step/EndWord 和到达时间。尾部补 2 秒静音排空，再等待 2 秒；尾部和发送迟到明确记账，不发送人工让轮标记。

`main` 核对历史音频 SHA256，先用 dev 样本预热，再串行采集五例 test。每例保存原始接收和发送计划，manifest 内的 Word 直接来自原始消息，保留文本、到达时间、原始文件摘要和音频来源；不用累计文本反推词边界。服务二进制与配置摘要一并冻结，异常保留已写文件并返回失败。

在远端 conda `interclarify-dev` 中运行：`python scripts/remote/capture_kyutai_words.py --url ws://127.0.0.1:31627/api/asr-streaming --manifest /path/endpoint-b4d12d6/manifest.json --server-binary /path/moshi-server --server-config /path/config.toml --output /path/new-capture`。使用冻结本地配置中的公开 `public_token` 请求头认证；首轮缺该头的 HTTP 401 原样保留，不改变服务授权配置。必须在 vc 单卡作业内启动冻结 Rust 服务；输出目录不可已存在。该脚本不调用 LLM、不训练、不生成新基础对话。
