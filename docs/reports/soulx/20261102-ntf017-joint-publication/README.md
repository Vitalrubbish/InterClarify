# NTF-017：160ms联合快照交付

日期：2026-11-02启动，2026-11-03完成。用户明确启动后完成本地实现、契约验收和架构图同步，工作单已归档。没有运行GPU推理或连接远端服务器，没有接入LLM／CoT／TTS，也没有切换现役Agent。NTF-020回答交接及018／019真实模型验收继续待实施。

## 最终行为

同一session／turn的每个160ms源批次，只在SoulX原生调用（设备同步、SenseVoice、服务及reset）和X2对应两个80ms LISTEN／DECODE步均完成后，一次向SharedContext提交闭合正文、五状态及真实进度。第一帧闭合组只暂存；WAIT无新字也提交完整批次，保留原正文和文字时间。前端active_output／stop_output及同步消费者回调已移除，下游自行读取共同快照。

下一批模型开始必须晚于本次联合提交成功。模型、网络、日志、消费者及complete ready不占Context锁，也不成为推进条件；独立生产者按真实时钟继续入账，原800ms／4MiB上限保持。各路available_at保留实际时间，新正文与状态共享batch_published_at；模型调用、先完成侧等待、提交及消费者读取可分别计时。

## 代码与接口

| 文件 | 交付 |
| --- | --- |
| [shared_context](../../../scripts/runtime/shared_context.md) | 联合事务、真实span／身份／回执／组数／前缀校验、当前快照副本、单条交接元数据比较更新及关闭终止保护 |
| [dual_audio](../../../scripts/runtime/dual_audio.md) | 唯一当前批次暂存、两路完成后提交、成功后释放、失败诊断及分段计时 |
| [native_soulx](../../../scripts/runtime/native_soulx.md) | 状态回调只暂存，完整原生调用结束才出完成回执，删除前端停止旁路 |
| [independent_x2](../../../scripts/runtime/independent_x2.md) | 80ms真实EOS组及进度暂存、完整回执、内部解码与Context已提交数分开 |
| [x2_teacher_frontend](../../../scripts/runtime/x2_teacher_frontend.md) | 历史教师显式legacy_frame模式，独立X2默认joint，话轮内不可互换 |
| [架构图](../../../figures/parathink_method.md) | 保留内部SenseVoice和独立X2，单一联合写入路径；nonidle由下游读Context后进入唯一输出运行时 |

对当前话轮只保留一份快照及至多一条交接元数据，不增加历史正文、patch、版本查询、消费ack或待发布队列。update_completion只预留比较更新事务，尚未实现候选目标、ready、去重、取消或超时的NTF-020自动判定；原始complete不能据此宣称允许正式回答。

reset保持原生数值与源采样连续，不清正文、不重置全局step_id。关闭、取消、任一路异常、缺失／重复／过期回执或容量失败均保留上一完整观察，不释放下一步。极小容量导致关闭元数据也失败时另记close_failure，内部有界终止标记仍拒绝迟到写入。EOF按实际存在帧数处理，右padding明示，开放组和各路未处理真实PCM留诊断，不补EOS或complete，tail_status始终unknown。

## 本地验收

使用已有interclarify-dev conda（项目文档允许复用），未新建或升级环境。实际执行：

```bash
conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -v
```

2026-11-03续做时重新执行，全量144项通过，退出0，无跳过；其中双路契约27项、原生协议5项、SharedContext7项。相对015／016的134项基线增加10项，并迁移了旧提前发布／独立停止断言。首轮全量出现4项历史X2教师兼容失败，修复固定发布模式后通过，未跳过旧用例。

验收覆盖两种先后顺序、首帧／nonidle／设备完成前不可见、统一发布与原始可用时间、连续WAIT、提交返回前禁止下一批、并发副本、交接元数据与新批次合并、关闭／迟到结果、回执及开始／可用／完成时序篡改、正文与字节容量、注入写入失败、reset连续性、EOF一／两帧、开放组失败、800ms／4MiB、推理期间生产者持续入账。原生对照仍使用官方实际方法和微型CPU依赖，未修改第三方源码。

PDF／PNG已重新生成并查看，LaTeX无溢出或缺字警告。修改Python的语法检查、同路径中文说明及Git空白检查通过；本地日志留在artifacts/ntf017-local/，不进入Git。检查仅证明本地合同；真实权重轨迹、GPU执行时间、预热、识别／状态质量和尾词覆盖由018／019验证，不把同步完成当成尾词必齐。

## 归档与下一步

本地工作单移至docs/issue/archive/NTF-017.md，沿用该目录不纳入Git的约定；任务原文可追溯合同提交74ccc13。当前活动顺序为NTF-020→018→019，不自动启动后续工作单或远端作业。
