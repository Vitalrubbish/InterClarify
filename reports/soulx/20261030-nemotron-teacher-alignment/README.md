# Nemotron 教师文字真实音频进度配对复测

2026-10-30，按用户指令只修第一个问题：将特殊ASR首块与SoulX主块按相同步号配对，改为按实际读取的PCM覆盖范围配对；保留原空增量强制改写、nonidle→idle分支、模型权重、教师文字编码、soft reset和样本配置。下游LLM／TTS不接入。

状态：修复源码 `98f347e` 已提交并推送，三轴各1条远端预检 `job-179337308502042131749-xuan-zhang` 退出0；309帧实际配对均覆盖主块截止并多出99ms，最大积压517.0ms。正式FDB30复测 `job-179337342342793117423-xuan-zhang` 已提交，质量待汇总。前次对照见[教师文字FDB30](../20261030-nemotron-teacher-fdb30/README.md)。

## 配对变化

旧原生ASR第一步窗口0—92.5ms，却配对SoulX主块0—160ms；后续ASR读取截止259／419ms，对应SoulX主块截止320／480ms，持续落后61ms。此前3185帧顺序验收证明执行先后正确，没有验收两路读取范围配对，这一限制在本次修正。

新实现将第一步作为startup，保留RNNT缓存与文字并单独审计释放，不预测SoulX状态；取第一个实际窗口截止达到主块截止的步骤配对。实际配对160→259ms、320→419ms、480→579ms，ASR额外观察99ms；SoulX自身640样本前瞻仍为40ms。原生ASR窗口形状和算法不变，99ms不是准确词级对齐或完整识别保证，也不是额外计算耗时承诺。

首块文字在第一次正常教师输入一次性消费，原生ASR步号与SoulX教师步号单列。每步发布Context后才允许后续解码；音频仍按80ms真实时钟包持续到达。EOF不足下一完整ASR窗口时关闭在线Context，随后单独排空；不补静音、不回填正文，也不伪造尾部状态。

## 验证与资源

本地既有conda：9项教师文字／屏障／采样配对检查、4项Context、5项原Nemotron服务、5项SenseVoice前端回归，共23项通过；启动脚本语法和Git空白检查通过。新增真实时钟替身回放检查启动文字、独立步号、释放次序和EOF无死锁，不代替真实模型质量评测。

远端单作业、1×4090、4CPU、32GiB，显存停止线22GiB、结果128MiB、时长1800秒、音频积压800ms。模型与两组conda只读复用。执行前队列为空，磁盘可用约831GiB。复用原FDB30 manifest，SHA256 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`，三轴各10条、原始音频513.1915秒。

## 证据位置

远端根 `~/parathink-soulx-duplug/`，冻结源码 `source/98f347e`，预检 `runs/nemotron-teacher-align-smoke-20261030-r1/`，正式复测使用独立目录，不覆盖旧结果。源码包经SFTP传输并核对SHA256 `6c0cd2dffc87b84b739231b811d946b16304689f525db91a63eb321f653ac67c`。

本地证据保存在 `artifacts/soulx/20261030-nemotron-teacher-alignment-smoke-r1/` 与 `artifacts/soulx/20261030-nemotron-teacher-alignment-fdb30-r1/`，逐帧JSON／CSV与正文不推送Git。实现及验收约定见[工作单入口](../../../docs/issue/README.md)和[同步方案](../../../docs/dev/SoulX-Duplug/nemotron_teacher_forcing.md)。
