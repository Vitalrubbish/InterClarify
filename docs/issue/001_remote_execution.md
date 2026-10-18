# Issue 001：官方 Word 输入远端核验任务单

状态：进行中。必验范围为一套官方控制配置下的历史五例；当前仅有资产扫描和诊断回放证据，尚未通过官方 Word 输入验收。

## 执行前准备

1. 核对历史五例的 Kyutai 原始 `Word` 消息和实际到达时间，冻结样本清单与哈希。若只有累计文本或字符增量，先补采缺失事件；不得从完整转写推算到达时间。Kyutai 只作参考输入来源，产品仍用 Nemotron/Kokoro。
2. 将两仓库源码保存到独立目录，冻结提交、工作树文件摘要、官方源码、checkpoint/tokenizer、依赖和输入摘要。
3. 先按 [001b](001b_runtime_comparison.md)修正现有比较器的 Word 缓冲和每拍拼接，再运行真实权重。现有 raw 与有界 complete_word 入口均不是官方 Word 验收命令，不能直接复跑后宣布通过。

## 唯一配置

| 项目 | 要求 |
| --- | --- |
| 官方源码 | `42893024ca90c8de8ac3ed624467ebc123512ff8`；server.py SHA256 见协议配置 |
| 输入 | 历史五例原样 Kyutai Word 事件与到达时间；逐词 strip，每拍用空格连接 |
| 起拍与时钟 | 首个非空 Word 到达后等待 600ms 开始首拍；串行执行，迟到单列 |
| 模型 | 同一发布 checkpoint/tokenizer，BF16、64-token 贪心、官方结束 ID |
| 回放 | 双方独立生成 assistant 历史，保留完整生成 IDs；不补标点、不发送 EOF 让轮信号 |
| 比较 | 窗口、prompt/生成 IDs、控制动作、历史和正文提交的首个差异 |
| 生命周期 | 集成在途 reset/cancel 独立核对旧请求、历史与响应代际隔离 |

固定输出和同 prompt 单步仅在出现具体差异时排错，不再要求完整词/raw、两种起拍或原样/去句读交叉组合。现有 160ms complete_word 超时残词发布不能冒充官方 Word。

## 资源、产物与放行

真实权重必须通过 `vc` 调度，起步 1×4090、8 CPU、32GB 主存，最多 4 GPU 小时；资源调整按实测记录。本地和远端均使用 conda，不在登录节点跑模型，不覆盖旧结果。

复用 `compare_layer1_runtime.py`、`run_layer1_runtime_comparison.sh`；修正 Word 输入后在同路径说明中登记准确命令。当前脚本仍仅用于历史诊断，不提供假定可运行的官方 Word 命令。

大日志保留远端 `data/runs/<run_id>/`，紧凑结果保存 `reports/layer1_training/<run_id>/`。报告包含输入/源码摘要、逐例时间线、缺测、退出码、资源、允许差异、集成生命周期证据及放行结论；原接话 0/5 是历史失败基线，不要求其变好才允许训练。

已有证据：[资产核验](../../reports/layer1_training/issue001-inventory-20261018/README.md)、[阶段诊断](../../reports/layer1_training/issue001-runtime-20261018/README.md)、[最新诊断](../../reports/layer1_training/issue001-validation-20261018/README.md)。保留原 run 和文件摘要，不把诊断成功改写成官方输入对齐。必要证据缺失或影响训练归因的差异未排除时，006 继续不放行。
