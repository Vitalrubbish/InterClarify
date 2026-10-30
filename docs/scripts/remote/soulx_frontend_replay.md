# 当前正文与状态的真实音频回放

对应 `scripts/remote/soulx_frontend_replay.py`。`prepare_manifest()`冻结既有FLEURS开发录音及完整／截断／重复／静音视图，附模型包英文示例；不引入FDB数据或阈值搜索，派生视图不是独立样本。

`CaseAudit` 将来源观察和状态采集写入Context之外的`*.source.jsonl`。每次`on_commit`后分别调用两次`get_user_turn()`，比较整帧副本，核对发布前采集的正文、状态、处理截止和标志；实际读取写入`*.snapshots.jsonl`。同时检查每个在线状态恰有一次联合覆盖，Context只有一条话轮当前值、不保留事件或正文版本。

`replay_case()`按80ms真实时钟送包，单模型在途、800ms队列上限；每160ms音频步骤联合发布。合成尾部先标drain，状态和文字仅诊断，不回填在线Context。结束时核账已处理真实采样与未处理缓冲，关闭保留最后正文。

`main()`复用固定加载器、上游、SoulX与SenseVoice权重和conda；预热三块静音音频及一次ASR后开放回放。每条音频重新建立独立逻辑话轮。默认realtime模式；causal模式只用于明确标记的限速功能诊断，不宣称实时吞吐。

结果保存配置、摘要、`progress.json`／`result.json`，报告联合写入次数、实际文字变化次数、状态、gap、消费者一致性、状态到联合发布耗时、排队与显存。输出替身仅检查停止投递，不证明实际停播。passed只表示管道检查通过，不表示转写或状态语义达标。
