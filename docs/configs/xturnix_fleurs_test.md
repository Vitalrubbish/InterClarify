# XTurnix FLEURS 测试配置

`configs/xturnix_fleurs_test.json` 冻结 XTX-002—006 使用的两组件协议。它不是运行入口，也不包含模型权重或凭据；回放客户端、预热探针和作业脚本都以该文件为准。

## 固定内容

| 部分 | 冻结值 |
| --- | --- |
| ASR | `nvidia/nemotron-speech-streaming-en-0.6b`，revision `ebe59e5a817142986528bbbee5dba8db7b38ed50`，EN160、FP32、lookahead 1 |
| ASR 传输 | 16 kHz 单声道 PCM16LE，80ms 包；160ms 模型分块与传输包分开记录 |
| ASR 服务 | 轮询 50ms、单请求 30s、单活动会话、30s 有界积压、EOF 2s 解码静音 |
| XTurnix | `xcczach/xturnix-pt`，revision `d4b0403e5a6744b46fa7602b6d77bbac2768d5b5`，FP32 |
| 控制动作 | Listen 下只允许 `<|start|>`、`<|keep|>`；两动作分数取最大值 |
| 上下文 | 官方 `max_seq_length=2048`，超限失败，不静默丢弃末条用户消息 |
| 归一化 | 仅去最后一条用户消息末尾的 Unicode 标点和相邻空白；内部标点、大小写和原始 ASR 保留 |
| 调度 | 单会话最多一个在途控制请求；排队容量 1，保留最新前缀并丢弃尚未开始的旧观察 |
| 回放 | 影子 Listen，start 后不关闭 ASR；5 秒静音尾窗；5 秒主窗口；EOF 只做排空 |

## 停顿策略

本轮 `pause.enabled=false`，不注入 `<|pause|>`。冻结的 Nemotron 服务没有提供可直接使用的因果分段事件；独立 VAD 尚未在本工作单元内设计、验证和冻结。EOF、文件时长、参考文本、离线最后 token 和事后对齐均不得作为停顿来源。

该决定不阻塞主指标：ASR 文本版本变化仍触发判断，提前 start 会被保留。未来若要启用 `<|pause|>`，必须先冻结因果 VAD 或真实上游分段事件，并在正式测试前完成协议验证；不能临时用文件末端补点。

## 资源与证据

准备阶段最多 4 CPU、8 GiB RAM、下载并发 2；推理最多 1×24 GiB GPU、8 CPU、32 GiB RAM、batch=1、单作业、单活动录音、4 小时；新增资产≤10 GiB，trace/结果≤2 GiB，启动空闲盘≥30 GiB。

`evidence` 段列出必须保留的字段：ASR 会话、版本、原始/增量文本、接收单调时钟、暂停与 EOF 阶段；控制请求 ID、输入版本、原始与归一化文本、状态、动作、分数、发送/接收时间；加载耗时、峰值 RSS 和 GPU 峰值占用。缺失以失败或 null 记录，不填 0。

配置的运行时路径是远端固定位置；更换节点或目录时必须显式修改并重新验证，不能由环境变量在正式回放中静默覆盖。
