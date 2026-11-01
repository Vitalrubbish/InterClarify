# NTF-007 教师文本纯追加与三轴预检

2026-11-01。源码`e54a9fe`，远端作业`job-179351349759341098658-xuan-zhang`，run `ntf007-teacher-smoke-20261101-r1`。本轮删除教师文本门控、`_revise()`、KV检查点、输入embedding账本及三项缓存上限，改为每步新增片段直接追加；本地104项通过，远端三轴各1条预检3/3完整、退出码0。

## 范围与输入

- 固定输入仍为FDB30 manifest SHA256 `403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cde4f3c07`，本轮只运行三轴各1条。
- 配置`configs/nemotron_teacher_append_only.json`：`control_mode=official_format_append_only_teacher`、`text_path=append_only`、soft reset、空增量规则和nonidle→idle规则保留；不再设置序列、修订或重放上限。
- 单并发、1×4090、4CPU、32GiB、显存22GiB停止线、1800秒、输出128MiB；模型、上游和两组conda只读复用。

## 实现

`TeacherTextBuffer`以控制文字累计值为基准，只把新增字符片段编码一次并追加到教师token序列；最后一个未完成词会重新分析用于审计，历史token不再改写。`process_step()`不再做门控前向，提示（仅首次）、前步状态、音频、本步文字和EOS一次前向；`text_commit_index`单调递增，`tail_replace_tokens`只统计本步追加在序列末尾的尾部token，范围越界立即报错。

保留音频覆盖配对、首块92.5ms单独释放、空增量计数、状态规则、远场拒绝、软重置、回看与40ms前瞻。`close()`保留最后正文和未完成尾词诊断，不追加补算。

## 本地验证

`unittest discover`共104项通过。新增用例覆盖：增量片段追加、历史token逐字节不变、尾部范围越界报错、无`_revise`／检查点／账本属性、空文本块保持为空、关闭不追加上下文前向；原音频配对与屏障用例继续通过。

## 远端预检

| 样本 | 帧 | 注入token | 尾词重编码次数 | 尾词token | EOF未完成尾词 | 最大积压ms | 状态计数 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 接话ID102 | 73 | 41 | 1 | 21 | `know` | 555.0 | idle42/nonidle26/incomplete2/complete3 |
| 停顿ID127 | 61 | 59 | 3 | 28 | `anybody` | 227.1 | idle23/backchannel2/nonidle31/incomplete2/complete3 |
| Synthetic打断ID104 | 175 | 40 | 1 | 21 | `guard` | 227.7 | idle140/backchannel1/nonidle30/incomplete2/complete2 |

逐帧独立审计通过：

- 每帧`control_text`严格以上一帧为前缀，后缀等于`delta_text`；最终`delta_text`拼接与`control_text`一致。
- `text_commit_index`逐帧不减，且等于累计`text_injected_tokens`；无`cache_revision`、`gate_open`等旧字段。
- `raw_delta_text`拼接与关闭时Nemotron原始正文一致；非空片段没有跳过注入。
- 三例最大积压均低于800ms停止线；本轮是功能预检，不作30条实时或状态质量结论。

## 限制

- 三轴各1条只验证append-only协议、KV长度和配对顺序，不替代NTF-009的固定30条延迟与状态对照。
- 跨步词片段按新增字符编码，拼接结果可能不等于整词一次性分词；这是纯追加、无重放合同的明确代价。
- EOF时最后一词仍可能停留在未注入尾部（本轮的`know`、`anybody`、`guard`），按单子约定保留诊断，不补算或回填。
- 本轮仍未接入NTF-008的单块音频缓冲与`A_n→T_n→EOS`逐帧对齐；发布延迟和打断时机由后续单验收。

## 证据

本地`artifacts/soulx/20261101-ntf007-teacher-smoke-r1/`，证据包SHA256 `5c359b3392b477ffb9aa51efa54f4e439bc6601ed385b2826441f3a8ad17e18a`；远端`parathink-soulx-duplug/runs/ntf007-teacher-smoke-20261101-r1`。SFTP回传摘要核对一致。
