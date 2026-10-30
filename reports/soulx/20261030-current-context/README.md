# SoulX＋SenseVoice 当前值写入实现

2026-10-30，按用户指令撤下Nemotron＋SoulX组合，完成官方SoulX＋SenseVoice前端的当前值写入。每处理一个160ms音频块，将最新话轮全文与本块原生状态联合覆盖到SharedContext；修订直接替换旧正文，不保存历史正文版本，不使用320ms定时器。

## 实现与回退范围

- `SharedContext` 改为每话轮一份当前观察，提供开轮、整帧覆盖、原子副本读取、关闭与受控释放。取消正文版本、patch、事件环和游标。
- `SoulXFrontend` 在ASR返回时只更新前端草稿，在官方外层状态处理结束后联合发布，包含complete分支追加的整段识别。reset保留逻辑全文和未处理音频；无新增文字仍更新状态。
- SenseVoice原始数字、标点、空格与标签采集保留；无法可靠拼合时明确gap，不用短窗口替代整轮全文。有效nonidle直接停止路径保持即时并按输出去重。
- 移除Nemotron组合适配器、worker、组合／FDB探针和运行脚本、专用测试及对应实现说明；旧设计标记撤回，报告和原始结果保留，源码由`9fb5319`追溯。独立Nemotron ASR服务及旧TextTurn运行时没有删除。
- 回放检查迁移到当前值接口，每次提交由两个读取调用核对整组数据，外部诊断文件允许保留观察轨迹，SharedContext本身不保存这些历史。

当前接口示例，`model`为已按冻结加载器载入的官方模型：

```python
context = SharedContext()
frontend = SoulXFrontend(model, context, session_id="s1", turn_id="u1")
frontend.feed_audio(pcm_float32_16khz)
current = context.get_user_turn("s1", "u1")
# current["text"], current["state_token"], current["state_accepted"]
```

160ms是处理音频步长，不是墙钟返回间隔承诺；80ms单包未满足处理条件时不会制造状态。下游Layer1／2、LLM状态编码和真实TTS未接入。Context覆盖不会自动改写LLM已读输入。

## 本地验证

使用既有`interclarify-dev` conda，相关检查共17项通过：SharedContext当前值3项、SoulX前端5项、旧TextTurn Context回归4项、独立Nemotron ASR服务回归5项。另对迁移后的`CaseAudit`执行开轮、两帧联合发布及关闭，两个读取者各取得4次一致快照。Python语法和回放shell语法检查通过。

关键场景包括旧词改写／删除、无新增字仍更新状态、并发读取不混帧、complete后的整段识别与reset顺序、float32与原始标签、远场拒绝、排空隔离、直接停止幂等。轻量模型替身只验证协议与调用顺序，不代表真实识别或状态语义质量。

## 远端验证状态

用户随后明确授权启动远端测试，作业`job-179333689216596649227-xuan-zhang`已退出0，六视图全部通过当前值写入检查，269帧联合覆盖，见[远端测试报告](../20261030-current-context-test/README.md)。下文保留此前实施交付时的资源核查记录，不再表示测试尚未进行。

已通过现有SSH入口只读核对远端队列与磁盘。核查时另一个项目作业`job-179333188185739475373-xuan-zhang`正在运行，占用2GPU、12CPU、64GiB；没有取消、修改或抢占该作业。按单活动作业约束，本轮未提交新的真实模型回放，不能宣称GPU验收通过。启动空盘约832GiB，满足30GiB前置要求。

真实模型入口已迁移：`scripts/remote/soulx_frontend_replay.py`与`scripts/remote/run_soulx_frontend_replay.sh`；任务范围与资源见[检查任务](../../../docs/dev/SoulX-Duplug/frontend_audio_check.md)。资源允许时用独立冻结源码、现有六视图manifest、唯一run ID提交1×4090／4CPU／32GiB、最长1200秒的调度作业；设备显存22GiB、结果128MiB、输入积压800ms，触限失败。无需下载或复制模型。

旧六视图已有窗口拼合gap、低幅度识别和未覆盖状态限制；当前实现保留缺口标志，不以存储覆盖正确性代替ASR和状态准确率。
