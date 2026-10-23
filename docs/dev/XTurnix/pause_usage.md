# XTurnix 原生 pause 用法核查与诊断

更新：2026-10-24。用户要求检查原生 `<|pause|>` 并实际尝试，作为 XTX-014 的首个机制诊断；不训练模型，不切换现役控制器。训练工作单归档及 ASR 时间路线继续保留。

## 1. 核查结论与来源

固定官方 X-Talk `5f0d9959edf1026588246efbed827b078cbb114c` 的 [xturnix.py](https://github.com/xcc-zach/xtalk/blob/5f0d9959edf1026588246efbed827b078cbb114c/src/xtalk/models/turn_detector/xturnix.py)。本地参考 fork 的该文件与官方逐字节核对，不修改参考仓库或其现役路径。

- `speech_pause=True` 设置 `speech_pause_seen` 和 `pending_pause_offset`，当前末尾先不写入 `<|pause|>`。
- 同一用户之后产生新文字时，才将 pending pause 写入之前的偏移，成为句内停顿标记。相同偏移不会反复插入，当前尚未续说的停顿保留 pending。
- Listen 下，模型原始动作 start 且 pause gate 已打开，才映射为实际 start。pause 可以放行缓存 start，但不能把缓存 keep 转为 start。
- 官方同一段对话/状态在首次出现 pause 时可复用先前原始动作，无需把末尾改成 pause 再请求模型。
- 单独 `async_detect(speech_pause=True)` 会更新状态但立即返回 IDLE；要经过推理/映射路径，需要像官方 ASR 管理入口那样传入当前文本。后续适配不能只发一个没有文本的 pause 调用就假定已经执行闸门。
- `speech_start=True` 关闭 gate；start 有一次性 latch，避免重复 pause 造成重复启动。停顿 token 本身不包含连续静默毫秒值。

论文预训练在两个用户片段间插 pause，不跨说话人变更插入；Listen 标签又按下一个时间线 token 是否仍属用户决定。因此用户续说前的 pause 往往对应 keep，不能把它当作“句末一定 start”的正向标志。[论文构造规则](https://arxiv.org/html/2610.04400v1#S4.SS1)。此前直接在句末补 token 的探针只说明该输入会抑制 start，不代表已经验证了官方 pending/gate 用法。

## 2. 本次尝试

在远端 conda 调度 GPU 作业中，复用冻结 PT、FP32、官方 pipeline 和 2,048 token 合同。实现对官方 pending/gate 合同的轻量回放，不加载完整 X-Talk/vLLM 服务，不宣称完整框架集成通过。

数据只取上一轮 dev 中至少两个停顿观察的前 20 个原话轮（按话轮 ID 的 SHA256 排序），使用已有冻结输入，无新数据下载。按已有参考前缀与停顿点构造 text→pause→续说事件；旧 pause 仅在新文字到达后进入模型，当前停顿仍保留 pending。再加 3 条明确标注为人工脚本的 sanity 轨迹，覆盖可 start 问句、未完后续说和重复 pause。

同一轨迹比较三种固定条件：不在文本历史中插 pause、官方 pending 插入、直接末尾插入。三者均使用相同 pause gate、默认 0.5 动作规则和一次性 start latch；差别仅在模型可见的 pause 位置。完整相同模型输入可缓存分数，保留真实模型调用数量。只用 dev，不重新检查旧 test 选阈值。

参考停顿属于离线机制刺激，不是新 ASR 产生的静默事件；人工 sanity 无真实音频。此实验可以核实 token 和 gate 行为，不证明 ASR 静默估计有效、在线时延改善或控制质量达标。后续将 ASR 无增量计时映射为 pause 事件仍需因果验证，不能使用 EOF 补点或解码补零。

## 3. 交付与边界

交付本次输入清单、源码/模型摘要、事件级模型输入摘要与分数、pending/gate/latch 状态、原始动作与映射结果、调用计数、资源与退出证据。保留失败/null，不为提高 start 比例调参，不将复用 dev 当作独立测试。

作业最多 1×24 GiB GPU、8 CPU、32 GiB RAM、batch=1、一个活动作业、超时 15 分钟；复用现有 conda，不下载权重或音频。既有磁盘和阶段累计预算继续适用。Speak、CoT、Layer 0/1/2、TTS 及播放器均不执行。
