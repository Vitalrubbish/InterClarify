# NTF-054 复测失败原因调查

后续用户已通过NTF-057明确取消本次完整系统复测的一致性检查并要求重提，不实施下文建议的RNG兼容修复。本文保留调查时的原始结论与建议，当前运行合同以NTF-054最新修订和r3记录为准。

2026-11-05，NTF-056。**smoke 失败的根因已由真实权重实验验证：跳过 complete 整段识别同时省去了 fbank 的随机数消耗，导致后续短窗使用不同的 dither 噪声，违反了本轮“其余短窗识别完全一致”的合同。** 自动衔接另因调度接口连接失败、查询无重试而退出，两者独立。

本次只新增诊断工具与调查记录；固定推理提交仍为 `65d15e6`。NTF-054 的三条 smoke、正式30条与 TOR／延迟评分尚未恢复，原验收条件保持。

## 1. 原失败现场

smoke-r2 作业 `job-179387030286102615198-xuan-zhang` 已完成模型加载及两轮完整预热，在 `full_warmup()` 的 `compare_native()` 阶段失败，退出1；三个 smoke 样本为0/3。不是从 TOR 分数判断失败，正式样本尚未执行。

重新读取完整 `native_equivalence.json`，两路均为59步、275条轨迹。第27步整段服务识别缺失及服务文字为空，属于已授权差异；此外有以下三处未授权短窗差异。以下 step／trace 均从0计数。

| step／trace | 官方参考 | 跳过路径 |
| --- | --- | --- |
| 40／192 | And moving into higher education back. | I moving into higher education back. |
| 43／208 | If moving into higher education back in your home. | Of moving into higher education back in your home. |
| 44／213 | If moving is a higher education back in your home country. | A moving is a higher education back in your home country. |

34次短窗的 PCM 摘要均一致；59次音频 token、123次状态模型输入／logits、59次规则后状态，以及所有步的控制正文、reset 缓冲和其余服务字段一致。本例中原生文本整理消除了差异词对后续状态输入的影响，但对照合同还要求原始短窗识别一致，因此拒绝放行是正确行为；不能由“状态恰好一样”推定其他音频也无影响。完整差异及现场摘要见 [failure_audit.json](failure_audit.json)。

## 2. 为什么设了 seed 仍会不同

远端实际依赖为 FunASR 1.2.6、PyTorch／Torchaudio 2.6.0+cu126。读取安装目录原文件后确认：

1. `models/sensevoice-small/config.yaml` 没有指定 dither；`WavFrontend.__init__()` 默认 `dither=1.0`，诊断中实际值也为1.0。
2. `WavFrontend.forward()` 把音频传给 Kaldi fbank，后者在 dither 非零时调用 `torch.randn`，向每个分析窗加入噪声。该实现也可在 [Torchaudio 2.6.0 官方源码](https://docs.pytorch.org/audio/2.6.0/_modules/torchaudio/compliance/kaldi.html#fbank)核对。
3. 原生随机缓冲使本次输入保持 float64；特征前端在 CPU 上取噪声。`torch.inference_mode()` 关闭梯度记录，不取消显式的随机数调用。
4. [compare_native](../../../../scripts/remote/native_frontend_probe.py)只在每路回放开始时设 seed42；[complete_text](../../../../scripts/runtime/native_soulx.py)跳过整段调用时只记录事件并返回空文字，没有保持该调用的 RNG 副作用。

第27步被省去的音频长97280样本。官方路径提取其特征后，CPU RNG 已向前推进；跳过路径仍停在调用前的位置。接着即使送入相同短窗 PCM，也会取得不同噪声和特征。因而相同初始 seed 只能保证相同调用序列复现，无法保证删除一次随机调用后仍逐次一致。

这里变化的是 PyTorch CPU RNG。原生 reset 使用 NumPy RNG，本轮 reset 后的三个缓冲摘要一直相同。不能把该故障归因于 PCM 漂移、reset 缓冲变化或执行线程迁移。

## 3. 远端因果验证

诊断作业 `job-179388371390743074870-xuan-zhang` 于21:01:54提交，在 `d6-hpc-gpu-059` 串行运行两组真实权重对照。复用同一冻结源码、资产、预热语音、主线程与2线程／interop1预算，保留现有对照的全部条件。详见[诊断脚本说明](../../../scripts/remote/diagnose_native_asr_rng.md)、[提交记录](diagnostic_launch.json)及[诊断摘要](diagnostic_summary.json)。

| 检查项 | 原始跳过路径 | 仅补齐被省略调用的 CPU 特征提取 |
| --- | --- | --- |
| 与原失败 comparison.json 完整内容一致 | 是 | 不适用 |
| 短窗 PCM 一致 | 34/34 | 34/34 |
| 短窗调用前 CPU RNG 差异 | 13/34 | 0/34 |
| 短窗特征差异 | 13/34 | 0/34 |
| 短窗文字差异 | 原来同样3处 | 0处 |
| 原有275条轨迹对照 | 失败 | 全部一致、通过 |

干预路径在第27步只执行 `extract_fbank`，丢弃特征，不执行该次 SenseVoice 模型，不恢复服务正文。补充调用与官方整段调用的特征摘要、RNG 前后摘要完全相同；后续所有短窗恢复一致。因此，省略特征提取引起的随机数偏移足以解释这次失败，无须用 GPU 数值波动或隐藏缓存假设解释。

更早的偏移可直接看到：第30步第一次后续短窗，官方调用前的 RNG 摘要为 `0ad1696b…`，跳过路径为 `548df565…`；二者分别就是整段识别调用后与调用前的状态。该步文字都为空，直到第40步才首次出现可见文字差异。故第40步是首次文字差异，不是随机状态开始偏移的位置。

作业约149.65秒完成，CPU峰值RSS约8.57GiB，GPU分配峰值4774.61MiB、保留峰值4910MiB，总输出约0.48MiB，均低于单卡、4CPU／32GiB、1200秒、22GiB显存及128MiB输出上限；随后队列为空。这里只验证原因，没有重新运行 X2／下游生成、固定30条或评分，也不提供修复后的性能结论。

## 4. 自动衔接为什么提前退出

衔接脚本在17:49:33调用 `vc list` 时，调度 API `10.24.18.34:6443` 拒绝连接。`vc` 在处理该错误时又触发内部 `NameError: ps is not defined`，最终退出1。[Campaign.active](../../../../scripts/remote/fdb30_retest_followup.py)直接使用 `subprocess.check_output()`，没有查询重试，异常上抛后把 campaign 标成 failed。

此时 smoke 仍由调度器独立运行，后来在约19:00因控制对照失败退出。因此，修复查询重试只能恢复跟踪能力，无法使这份 smoke 放行；修复 ASR 一致性也不会让已退出的衔接进程自动复活。

r1 只有“离队且无成功退出标记”的既有证据，仍不足以判断是删除、调度故障还是其他退出。本次没有将 r2 的已证实原因追溯套用到 r1。

## 5. 修复建议与恢复顺序

在当前严格合同下，优先验证“省去整段 ASR 模型与 fbank 计算，同时按冻结实现仅补齐该次 CPU RNG 消耗”的兼容修复。需要依据实际窗形状、dtype与依赖版本验证推进结果，不能只按样本数猜一个偏移，也不能每步重新设 seed。此次补做完整 fbank 是定位手段；此前长尾主要嫌疑包含 CPU 特征提取，不宜将它直接作为性能修复交付。

如果选择独立的短窗随机流或关闭 dither，应先修订研究／对照合同，再比较真实权重与固定30条；这些方案会改变原始特征生成行为，不能当作现有合同下的无差异修复。直接忽略短窗文字差异或放宽比较字段也不解决随机状态耦合。

衔接端应对只读队列查询增加有限次数重试与退避，持续失败则记录“调度状态未知”并停止；查询失败不能按空队列处理。不要对结果不确定的 `vc submit` 直接自动重提，以免重复占用资源。

建议先完成 RNG 兼容修复及查询重试，补充随机副作用回归，再通过相同真实权重对照与三条 smoke，最后按原顺序恢复固定30条和TOR／延迟评分。NTF-054 在这些步骤完成前保持未完成。

## 6. 证据保存

原失败、安装依赖源码和诊断原始输出已回收到本地 `artifacts/soulx/20261105-ntf054-investigation/`。远端保留原 r2 目录与 `analysis/ntf056-native-asr-rng-20261105-r1/`。两份 JSON 审计保存逐文件 SHA256；诊断基线完整复现原始 comparison，原失败现场未被覆盖。
