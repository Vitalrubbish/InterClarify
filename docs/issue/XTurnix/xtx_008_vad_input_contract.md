# XTX-008：冻结 VAD 辅助输入协议与隔离训练环境

状态：条件性后续，尚未授权实施；XTX-007 已完成，用户本次仅同意 XTX-009 首轮来源审核。前置：[XTX-007](../archive/XTurnix/xtx_007_training_feasibility.md)明确同意进入本项后，复用并重新核验 [XTX-002 冻结资产](../../../reports/xturnix_fleurs/20261023-xtx-002-protocol/README.md)。依据：[训练可行性方案](../../dev/XTurnix/training_feasibility.md)，共同资源与范围见[工作单入口](README.md#训练阶段共同边界)。

## 目标

为 XTurnix 提供真实、因果且可复现的发声和时间观测，建立独立训练环境。VAD 只提供观测，控制动作仍由 XTurnix 判断。

## 工作内容

- 只读复核 PT 的 revision、权重、tokenizer、六个既有特殊 token 和 2,048 token 上限；冻结训练与推理依赖，使用独立 conda 环境，不覆盖现役环境。
- 选定并锁定一个因果 VAD 的源码、权重与运行参数，确定音频分块、时间戳、发声/静音切换及静音时长观测的更新规则；参数不得由正式测试选择。
- 定义版本化外部观测块、缺失值与可见时间，区分实际静音、用户仍在发声但转写未到达、ASR 新前缀与真实 Listen/Speak 状态。禁止将无文本增量当成静音。
- 在保留官方文本基线的同时，实现扩展输入的预处理与序列化，明确其与官方固定 system prompt 校验的差异；外部观测不伪装成用户发言，不新增词表或静默截断。
- 定义事件触发、同一会话单个在途请求及容量为 1 的最新观察队列；静音时长必须作为新观测进入输入，不通过重复不变文本表示时间。
- 用少量人工可核对的轨迹验证实际语音、句内静音、ASR 延迟及恢复发声；记录 VAD 与 ASR 到达时序，不从 EOF、文件长度或离线末词位置补点，不在句末拼接合成 pause。

## 交付

拟新增 `configs/xturnix_training.json`、`scripts/remote/setup_xturnix_training_env.sh` 和 `scripts/remote/xturnix_training_inputs.py`；分别配套 `docs/configs/xturnix_training.md`、`docs/scripts/remote/setup_xturnix_training_env.md` 与 `docs/scripts/remote/xturnix_training_inputs.md`。实现可复用已有模块，最终路径在对应说明中登记。

协议文档明确输入字段、时间与状态来源、触发规则、超长处理及训练/推理一致性；环境与小轨迹核对报告保留版本、哈希、资源及失败。只增加必要的因果性和序列化契约测试，并配套同路径测试说明。

## 验收

- [ ] 模型、VAD、tokenizer、环境和输入协议均可追溯；新环境未改动现役资产。
- [ ] 发声但 ASR 暂无增量不会变成静音，恢复发声可结束旧停顿状态。
- [ ] 末端无 EOF 补点；外部观测没有越过当前可见截止点。
- [ ] 官方基线和扩展版本分别可复现，目标动作 token 的输入位置清楚。
- [ ] 新观测触发与有界队列规则明确，VAD 不直接触发 start/stop 或播放。
- [ ] 代码、配置、必要测试与对应中文说明齐备，完成后立即归档。

## 边界

不训练模型，不把 VAD 等同于语调理解，不改变 XTX-001—006 的冻结输入与协议。真实模型和 VAD 集群验证仅在受限远端作业内执行；不接 CoT、Layer 0/1/2、TTS 或播放器。
