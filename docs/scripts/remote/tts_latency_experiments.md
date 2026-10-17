# TTS 同卡筛选驱动

`tts_latency_experiments.py` 在同一调度器分配的 GPU 上顺序运行 control_start、batch4、early_batch4、prefill8、prefill4、deadline200、control_end。每次只有一个 MOSS 服务，服务各自有 trace 和日志，模型/音色/采样/CPU 推理线程固定。GPU 采样在整个作业持续运行。使用独立 conda 客户端解释器，服务仍由原 launcher 进入固定 MOSS conda。

`arms` 定义单变量关系：batch4 对 control，early_batch4 对 batch4，三个文本门槛候选对 control；首尾 control 用于观察漂移。筛选用原固定集中的短答、澄清、长句三条，保留整句、100ms 增量及 600ms sparse。batch/early 测前两模式，文本门槛候选测 sparse；各 3 轮，首尾 control 覆盖三模式，总 117 条正式筛选响应。小集合不能声称完整质量/尾延迟验收。

`run_arm` 启动独立进程组、等待真实 health、按该 arm 各文本/模式预热，再调用相同基准逻辑。预热和正式目录分开；如正式区间仍有新图则报告编译污染，不剔除样本。每个 arm 设置明确的环境变量，不改固定上游 checkout、产品默认配置或现役环境。

`run` 登记源码/环境/GPU/模型锁，完成一个 arm 就写 `progress.json`，异常保留失败并继续能独立执行的 arm。每个 arm 的真实 WAV、逐响应 JSON、时间线和 summary 留在共享输出目录。`stop_process` 先 TERM，20 秒后 KILL，仅清理本任务进程组。最终 `experiment_summary.json` 保留各 arm 状态，非全部完成则非零退出。

启动参数 `--task-root`、`--output`、`--round1-root`、`--model-root`、`--reference` 必须为真实路径；`--client-env` 是当前 conda，`--port` 默认 18004。依赖/组件测试由节点 shell 在 driver 前执行。时间线的 sparse token 数来自服务，不能假定每个双词片段等于 2 token。报告与测试镜像同步更新。

`--only batch4 early_batch4` 支持独立修复复测，两个 arm 在同一新分配卡上配对；缺席的 control 不跨卡借用，subset 的首个 arm 标为无前置 control。原失败作业和原始日志保持冻结，不在运行中替换其服务源码。

`--suite combination` 运行独立的 81 条组合筛选：control_start / combined / control_end，各三文本×三模式×三轮。combined 显式 batch=4、early=1、tokens=4、wait_ms=0；control 保持原参数。不与默认 screening 的单变量设计混合，组合收益只归给整个配置。`--suite` 默认 screening，不改变既有作业；参数校验禁止请求不属于 suite 的 arm。
