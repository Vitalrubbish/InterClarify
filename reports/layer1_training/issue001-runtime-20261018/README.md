# Issue001 运行时对照阶段结果

原版参考server.py固定为42893024、SHA256符合登记值。参考控制循环执行原版AST，模型推理使用同一冻结BF16内核、64token贪心；原始IDs端点绕过集成prompt renderer。raw前缀通过已声明的输入适配合并为每窗一个Word；不声称复现Kyutai语音传输。reference与integration分别生成自身历史。

修复后的CPU固定输出对照 `runtime-fixed-r2`：raw/complete-word与session-start/first-nonempty四组，13、13、13、12拍，共51拍，prompt/生成IDs、提交历史、控制、停播和正文首次差异均null。complete-word最多暂存160ms、超时仅释放已到达字符，未补标点、未发送EOF边界。

真实权重 `runtime-r3-protocol` 作业 `job-179233084872492534656-xuan-zhang`：raw条件8拍对照通过；complete-word共同前7拍IDs一致，首次差异为测量截止时reference8次、integration7次请求，因此整轮退出1，不能标记完整对齐通过。双方逐拍时间线保留，末窗差异仍须按统一逻辑时钟和物理耗时分离定位；不据此认定模型兼容问题已解释，也不放松已登记标准。

加载顺序调整后，同一完整发布state strict恢复成功，71.32秒达到readiness，CPU加载阶段峰值RSS7850904KiB，GPU生成峰值约16.30GiB。此证据支持001d的部署加载修复，不替代005训练恢复和独立零更新数值核验。

首轮长作业留下部分结果但无正常退出码，终止原因未取得；其曾揭示duplicate_answer拦截导致历史丢失，以及参考EOS消费前收尾导致末拍缺失。原失败留远端。第二轮protocol/historical-1均在180秒readiness超时，退出1，不能直接归因OOM。对应失败日志与第三轮完整轨迹保留本目录，原件摘要另存。

当前仍缺历史五例完整重测、在途reset/cancel独立参考对照及末窗时钟归因；same-prompt单步模式已实现但未单独执行。001/006仍不放行，没有训练或新底座冻结。

逐拍JSON仅移除序列化空白，字段值保持相同；artifact_sha256记录远端原件摘要，compact_sha256记录本地紧凑副本摘要，原始大日志留远端。

后续更正：用户追问调用次数后，001e定位到共享模型服务逐token重复计算词表大小，造成明显掉拍。旧8/7不仅是末窗差异，两路吞吐均低于600ms目标；旧生成seconds未覆盖校验CPU耗时。旧结果仍保留，不作为正常实时性的证据。修复与重测见 `reports/layer1_training/issue001-validation-20261018/`。
