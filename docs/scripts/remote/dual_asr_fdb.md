# 双ASR固定FDB回放

对应`scripts/remote/dual_asr_fdb.py`。使用同一量化PCM分别送入独立Nemotron进程和SoulX线程，固定80ms实时到达，不等待本步发布。主线程持续领取解码快照并执行唯一配对发布；入口队列满、两路未读超800ms、发布超800ms或子线程异常均停止该条并保存失败及未发布证据。

`load_controller()`复用摘要冻结的官方加载器，实际加载SenseVoice；`run_case()`记录原始状态与联合帧、两路窗口、控制文字、队列/计算耗时和PCM计量。EOF不补音频、不强制whole-turn Nemotron；完整窗口处理后将未配齐状态写诊断，关闭并detach控制器。每条前恢复官方reset，逻辑话轮不跨样本。

`run()`核对原FDB30 manifest SHA256和音频文件摘要，先三轴各1条smoke，再按原清单回放30条；失败保留在固定分母。分析复用已有三轴边界与WER算法，发布延迟增加主块、完整观察截止及状态产生三个基准。真实模型仅由远端conda调度执行。
