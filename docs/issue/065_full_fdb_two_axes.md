# Issue 065：当前微调模型完整FDB两轴评测

状态：进行中，2026-10-21。用户明确要求在远端提交当前微调模型的完整FDB User Interruption与Smooth Turn-Taking任务。

## 冻结范围

使用FDB v1.0完整两个轴：synthetic_user_interruption 200例、candor_turn_taking 119例，合计319例，数量与官方dataset/README一致。远端原始输入约2.019小时；逐文件摘要和标注在提交前冻结，不使用旧25例子集或抽样替代。官方源码冻结为3e799c45a045256f47d5f1c9cda90157e2d2ec9e。

当前T2_R3_delayed_start checkpoint SHA256为266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346。运行采用首段300ms、后续1200ms、600ms micro-turn、跨请求KV复用、duplex_greedy_v1/repetition_penalty=1.0。X-Talk采用已发布d6dc3bff0a512d13f4352bce6105aec80b7f9960；系统backchannel继续关闭，单一仲裁与播放路径保持。

## 执行与评分

先在独立目录逐例实时回放319段完整输入，官方output.wav与原输入等长；5秒连续静音尾窗仅作诊断，不纳入正式评分。然后用官方Parakeet词级转写对齐，Smooth Turn-Taking运行官方smooth_turn_taking评分，User Interruption按官方裁剪插话结束前音频、执行TOR/Latency及GPT评分。Judge沿用固定上游gpt-4-turbo与现有兼容端点，标明实际身份，不冒称README表中的其他judge。

任务启动先验证评分环境、本轮输入3秒裁片及静音的官方对齐与judge可用性，避免完整推理后才发现依赖问题。凭据仅运行时读取已有忽略文件，不写入提交、任务环境或日志。官方评分的漏答与零有效回复/异常须保留，执行失败不能记通过。

资源：单作业2×4090/16CPU/64GiB，8小时硬限、并发1、回放及评分均串行；推理模型GPU0、ASR/TTS共用GPU1，推理后停服务再评分。输出30GiB上限、空闲盘至少50GiB，单文件8GiB限额。使用现役conda，不复制模型权重；官方对齐/评分复制至独立工作副本，不修改上游。

## 工作与完成条件

- [x] 完整319例清单、两仓库源码与当前权重身份已冻结。
- [x] 本地4项完整清单/暂存测试、脚本语法通过，评分预检入口就绪。
- [x] r1已接受但评分预检因文件大小上限退出；修复和独立r2重提由066跟踪，未开始正式回放。
- [ ] 推理、对齐、评分全部结束后回收逐例覆盖率与两轴官方指标、退出码和遗留问题，再归档。

本轮目标首先完成有效任务提交，不提前填写指标。后续319例全部结果交付前状态保持进行中，不因已提交就声称评测完成。

[提交与运行记录](../../reports/fdb/20261021-full-two-axes-r1/README.md)保留独立源码/输出路径与摘要，当前尚无两轴分数。

066修复：NeMo官方评分模型解包需要超过1GiB的单文件，调整至8GiB；临时文件放入输出/tmp，保持总磁盘和空闲盘限额。
