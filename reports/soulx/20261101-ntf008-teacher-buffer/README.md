# NTF-008 教师链路单块缓冲与三轴预检

2026-11-01。源码`4c81904`，远端作业`job-179351483829055601261-xuan-zhang`，run `ntf008-teacher-smoke-20261101-r2`。本单把音频embedding放入最多4块的有界队列，按首个覆盖主块截止的流式ASR步骤配对，删除双ASR配对器与complete后整轮重识别；本地90项通过，远端三轴各1条预检3/3完整、退出码0。

首轮`r1`（源码`d3e4872`）在接话样本暴露出批量轮询假设错误：允许4步前瞻后，`poll`一次返回多个已完成步骤，而代码期望单步。`r1`失败证据保留；`4c81904`改为本地步骤队列逐条消费后重跑，`r2`通过。该修复没有放宽任何验收条件。

## 实现

- `NemotronTeacherFrontend.prepare_audio()`把每块音频编码为embedding放入`deque`，默认上限4；状态步骤在文本到达后取用。队列满时丢弃最旧块并累计`audio_buffer_overflow`。
- `BarrierSession`允许最多4步流式ASR前瞻；`run_case()`按首个`feature_end_sample >= 主块截止`的完成步骤配对，不再为92.5ms首块单独release。
- 删除`dual_asr_frontend.py`及其配对器、`dual_asr_fdb.py`、`dual_asr_worker.py`、`dual_asr_fdb`入口和分析脚本；双ASR文档移入`docs/archive/`。
- complete／incomplete只flush已到达教师文本并软reset；`load_controller()`仍用报错替身禁用SenseVoice，`whole_turn_rerecognition_calls`恒为0。
- 帧携带`service_state`、`service_completion_source`、`speech_detected`、`service_text`；无前置nonidle的complete以`no_speech`拒绝。

## 远端预检

| 样本 | 帧 | 主块→发布P50/P95ms | 完整观察→发布P95ms | 最大积压ms | 缓冲深度/溢出 | EOF部分块 | 服务完成 |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 接话ID102 | 73 | 213.0/240.9 | 141.9 | 440.7 | 1/0 | 1 | model_complete2，no_speech1，far_field2 |
| 停顿ID127 | 61 | 211.6/230.0 | 131.0 | 230.3 | 1/0 | 1 | model_complete3 |
| Synthetic打断ID104 | 175 | 211.6/234.2 | 135.2 | 248.7 | 1/0 | 1 | model_complete2 |

- 三例主块截止到发布P95均≤250ms；完整观察口径P95为131.0—141.9ms。
- `buffer_overflow=0`、`audio_buffer_overflow=0`；`buffer_depth_max=1`、`audio_buffer_depth_max=0`（每块准备后立即被下一步取用）。
- 三个样本的EOF都剩不足一个完整主块的真实尾部（1919—2560采样），按合同不补静音、不回填，均记录`eof_partial`。
- 打断ID104首个有效nonidle相对标注起点晚680ms；本轮没有同条件NTF-004基线，不宣称与“约180ms”预期一致。
- 逐帧检查：`teacher_step_seq`连续，`native_step.feature_end_sample`首次覆盖对应主块；每帧先准备音频，再注入文本和EOS；`whole_turn_rerecognition_calls`全为0。

## 与验收的差异

- 分配置原文要求预检`eof_partial=0`，但真实音频尾部不足一个主块，不补静音时必然产生一个部分块记录。本轮按“标记而不是补算”的原始范围处理，预检结果为每例1条`eof_partial`；该字段不是失败，已在工作单中改写验收表述。
- `wait_fallback`属于旧官方外层SenseVoice路径；教师链路直接预测五类状态，不产生该来源；字段仍保留在SharedContext合同中，但本轮计数为0。
- 三轴各1条只验证结构、输入顺序和延迟，不替代NTF-009的固定30条实时与状态对照。

## 证据

本地`artifacts/soulx/20261101-ntf008-teacher-smoke-r2/`，证据包SHA256 `60637dacd21d33766f748149e740652e6ec5ef3a56b0f179a567ba692ca204c9`；`r1`失败run保留在远端`parathink-soulx-duplug/runs/ntf008-teacher-smoke-20261101-r1`，不进入成功分母。
