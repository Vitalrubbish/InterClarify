# Issue 001：冻结官方输入契约、基线与验收口径

状态：进行中。优先级：P0。002 已单独完成；004/005 可继续数据和加载准备，006 仍未放行。

## 目标与范围

按 DuplexCascade 官方的一套控制配置检查 X-Talk 集成是否正确，避免用训练掩盖协议错误。仅验收相同输入下的窗口、prompt IDs、完整生成历史、控制动作和正文提交，不要求未经适配的官方权重达到接话率目标。

官方固定源码为 [server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L422-L499)：接收 Kyutai `Word` 消息，逐项 strip 后入队，每拍用单个空格连接；首个非空 Word 到达后等待 600ms 开始首拍，空拍使用 no-voice。配置保持发布 checkpoint/tokenizer、BF16、64-token 贪心及官方结束 ID。

官方采用词级发布：Kyutai [ASR 实现](https://github.com/kyutai-labs/moshi/blob/main/rust/moshi-core/src/asr.rs#L217-L238)积累词内 token，遇到边界标记后发出 Word；DuplexCascade 不消费任意 raw 字符后缀，也不等待整句。本项目的 `complete_word` 会在 160ms 超时后释放残词，也不等同官方 Word。必验对照使用同一份保留到达时间的官方 Word 事件，不把现有两种诊断模式直接称为官方输入。

只运行上述一套配置和历史五例原样样本，不展开时钟、发布粒度或句读组合。单步和固定输出仅用于定位具体差异。Nemotron/Kokoro 仍是产品组合，Kyutai 仅提供官方参考输入；真实产品迁移和音频验收由 007/008 负责。集成在途 reset/cancel 单独检查旧请求、历史和代际隔离，不与参考输入交叉组合。

## 已完成

- [x] [001a 资产扫描](archive/001a_asset_inventory.md)：官方源码、checkpoint/base、tokenizer 与组件摘要已有记录，token IDs 已核验；许可审核尚未完成。
- [x] [001c 历史保持](archive/001c_runtime_history_preservation.md)、[001d 加载修复](archive/001d_checkpoint_load_memory.md)、[001e 校验耗时修复](archive/001e_prompt_validation_overhead.md)已归档。
- [x] 协议登记 UltraChat 来源、1,000/200/300 规模、三组继续训练、随机种子及最多两轮、72 GPU 小时上限；数据下载和实际切分归 004，训练参数短跑归 005。
- [x] 保存 EN160 官方权重接话 0/5 的[历史基线](../asr_official_input_retest.md)。已有固定输出 51 拍及 protocol raw 13/13、complete_word 12/12 均为诊断证据，不证明官方 Word 输入已对齐。

## 剩余任务与完成条件

- [ ] 核对历史五例是否保存原始 Kyutai Word 与到达时间，冻结样本清单和摘要；缺失时远端补采，不用完整转写反推在线词边界。
- [ ] 在现有比较器中直接支持官方 Word 输入，保留逐词 strip 和每拍空格连接；替换必验路径的 RawDeltaBuffer 拼接，不增加第二套控制器。具体实现与对照由 [001b](001b_runtime_comparison.md)负责。
- [ ] 单套配置下完成五例连续自由回放，双方各自生成历史；逐请求 prompt/生成 IDs、控制和提交历史一致，影响训练归因的未解释差异为零，失败与缺测完整保留。
- [ ] 留存集成侧在途 reset/cancel 的旧请求、历史和响应代际隔离证据；已有测试可复用。
- [ ] 完成资产许可审核与冻结清单，汇总源码摘要、输入契约、逐例结果、退出码和明确放行结论。

使用现有比较器和远端 conda/单卡入口，先修正输入契约再执行，见[远端任务单](001_remote_execution.md)。数值与时序容忍维持协议登记值；不补句号、不发送人工让轮信号或 EOF 标记。`training_released` 保持 false，计划收敛不表示验收通过。
