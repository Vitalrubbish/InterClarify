# 官方每拍输入配对复测

`scripts/remote/retest_asr_official_input.py` 只回放现有真实 ASR 轨迹到固定官方权重，不重新识别、训练或播放音频。来源为历史接话驱动的保留契约，避免建立第二个产品运行时。

`OfficialBridge` 把原 X-Talk runtime 的请求交给 HTTP 模型服务，启用 audit_prompt，记录真实 prompt IDs，并与独立 `reference_prompt_ids`（直接加载官方 tokenizer.json）逐条比较；official 臂不相同即判错误，legacy 臂保留差异作为证据。`HTTPModelProxy` 保持客户端与权重环境隔离。`replay_one` 按真实到达时间更新累计前缀，从首个非空输入后启动官方 600ms 时钟，每拍仍使用现有 MicroTurnAssembler 与 DuplexRuntimeAdapter。

`response_metrics` 按新 response 首正文计分，不把边界前正文续写或取消记为新答。`run` 固定模型/输入/源文件哈希，执行五个 ASR 配置、原始与去标点两种变体、五个样本；`--arm` 区分 legacy/official，输出每条 history、请求、事件、prompt 审计及 summary。`--configs` 和 `--variants` 仅用于明确的短跑，不改变默认完整矩阵；部分结果不能当完整复测。

默认观察边界后 12 秒，2/5/12 秒覆盖分别报告，标注仅用于离线评价。两臂各自生成历史，不能强塞另一个条件的 assistant token IDs。真实推理仅在远端 conda 和独占 GPU 上执行。

`verify_official_reference` 校验固定官方 server.py 的 SHA256，从 AST 中提取原版 user/no-voice/ChatML 追加块并仅执行该块，以真实 tokenizer 和混合历史验证独立 oracle；不启动官方语音服务器或另建产品运行时。实际生成器的 prompt IDs 在开始生成前回传，末拍取消也保留输入审计。

收尾修正：部分分片在观察窗结束强制取消末次 HTTP 生成后，后续请求不再完成。复测器改为先停止新增 ASR 输入，时钟在窗口末尾不再发新请求，允许已提交生成最多 10s 收尾；统计仍严格过滤到原 12s 窗口。无首文本时可取消等待时钟；收尾超时则整轮报错，不能冒充无回复。记录每例测量起点、收尾宽限耗时和窗口外请求数（必须为零）。此变更不证明产品打断取消接口已验收，相关故障仍单列。正式矩阵使用统一修正版本重新运行。
