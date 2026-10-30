# SharedContext 当前用户观察

对应 `scripts/runtime/shared_context.py`。`SharedContext` 每个逻辑话轮保存一份最新全文与当前 SoulX 状态，后续整组替换，不保存历史正文、事件环、版本、patch 或读取游标。旧 TextTurn 的同名 Context 独立保留，不受本次修改影响。

`open_user_turn()` 创建指定来源的空话轮，默认 SenseVoice，也支持 Nemotron；来源在话轮内固定。`publish_user_frame()` 校验来源、状态 ID、真实音频进度和大小限制，在短锁内替换整条记录。文字允许修改或删除旧词，重复／倒退音频块不能覆盖当前值。`get_user_turn()` 返回原子副本，读者修改副本不影响后续读取。

`close_user_turn()` 保留最后正文和状态并设置关闭原因；关闭后拒绝新帧。`release_closed_turn()` 显式释放已关闭记录。Condition 只用于短锁与变更通知，不保存更新队列。

默认最多128个话轮、正文65536字符、单快照256KiB；触限明确失败，不自动删除活动正文。接纳状态校验原生五类 token 与 ID，拒绝状态保留原因。开轮时尚无状态，以空值标明初始化，不伪造 idle。

调用方以单写者提交160ms音频处理结果，Layer 1／2在输入边界读最新值；慢消费者可能跳过中间状态。覆盖 Context 不会自动改写在途 LLM 的输入或KV。测试见[当前值检查](../../tests/test_shared_context.md)。
