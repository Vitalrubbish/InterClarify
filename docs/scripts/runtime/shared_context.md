# SharedContext 当前用户观察

对应`scripts/runtime/shared_context.py`。`SharedContext`按session／turn保存一份有界当前正文、五状态与真实进度，不保存正文历史、版本、patch或消费ack。默认上限128话轮、65536字符和256KiB快照，任何校验或容量失败都保留上一观察。

## 类与核心方法

`open_user_turn()`冻结唯一来源`x2_streaming_asr`和`joint`发布模式，初始化step_id=-1、空正文、未知状态及tail_status=unknown；话轮内不能切换来源或模式。

`publish_joint_batch()`只接收完整160ms批次：一条原生调用完成回执、按真实EOF长度存在的一至两条80ms回执及对应暂存回调。核对身份、步号、完成时序、原生代次、真实／合成采样span、WAIT／WORD与EOS组数、正文追加前缀和回调一致性。原生设备同步、服务和reset结束才是完成，入队和单独状态预测不能满足条件。

无新字时保留正文及其观察／可用／发布时间；新字随状态同取batch_published_at，各路available_at保留实际值。控制调用与每个80ms帧的开始、可用和完成时序均在提交前校验，缺失或非有限开始时间也不能进入当前值。状态主块、前瞻与X2进度分别保存，不按相同步号推定对齐。Context只存文本和采样元数据，不存PCM或开放子词；尾词保持unknown，coverage_complete不冒充全文完整。

校验后在短锁中复核最新话轮、连续批次、代次、组数和正文，保留当前话轮开闭状态，检查容量后一次替换。工作线程不能回写此前读到的整份快照。Context不提供逐帧文字或状态写入入口，所有前端更新必须经过联合批次。

`get_user_turn()`返回原子深副本；可选with_timing=True返回snapshot、read_started_at、read_completed_at和read_seconds，读取计时不写回当前值。`close_user_turn()`保留最后观察并关闭，迟到批次写入被拒绝。`release_closed_turn()`显式释放关闭记录。

所有时间使用注入的同一单调时钟。锁内没有推理、网络、磁盘日志或消费者回调。话轮边界检查见[SharedContext检查](../../tests/test_shared_context.md)，联合事务检查见[双路检查](../../tests/test_independent_frontend.md)。

关闭元数据本身也受快照容量限制。关闭入口先设置按话轮有界的终止标记，即使元数据写入失败也拒绝后续批次、旧帧；保留原完整快照，由协调器记录close_failure。release_closed_turn同时清理该标记，不形成历史队列。
