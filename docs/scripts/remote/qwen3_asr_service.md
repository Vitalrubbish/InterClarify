# `scripts/remote/qwen3_asr_service.py`

## 整体作用与协议

在独立 ASR conda 环境中加载一次 Qwen3-ASR，接受 16 kHz mono PCM16，按 session 返回累计转写。`POST /v1/session` 创建会话；`POST /v1/recognize` 接收 session_id、base64 audio、is_final，返回 text/language；`DELETE /v1/session/{id}` 释放；`GET /health` 检查存活。启动入口与配置仍为 run_xtalk_round1.py serve asr 和 configs/xtalk_round1.yaml。

## 类与核心方法

`RecognizeRequest` 定义请求体。`SessionState` 保存当前片段解码器、串行锁、片段内 committed_ids/visible_text、已结束片段 completed_text、segment_index、audio_samples 与累计 stalls。

`ASRService.recognize` 每个请求的音频只送入当前解码器一次。存在音频的片段收到 final 时先 flush，经过前缀检查后冻结当前可见文本，再用原流式参数新建解码状态。后续片段不携带上一段的 token，避免句末标点回写锁死后续续说。重复空 final 不 flush、不追加。HTTP session 保持不变，对外仍返回累计文本。声学暂停不是语义让轮，Layer 1 决策不变。

`committed_token_ids` 对已解析 state.text 重分词，扣住末尾 unfixed_token_num 个 token；不能处理带 language/asr_text 标签的原始串。重分词前缀不具备绝对稳定保证。`decode_token_prefix` 避免交付半个 Unicode 字符。`advance_committed` 同时校验 token 与字符串前缀，正常候选只延长可见文本；深层回改时保持原前缀并累计 stalls。final 同样不能绕过检查。段内深层回改仍可能停滞，必须查异常日志，不能声称所有 ASR 回改都已解决。

`join_segments` 在相邻 ASCII 片段间补空格，中文直接连接；不按重叠词去重，以免删除真实复述。不开 emit_committed_prefix 时允许片段内原始转写修订，但 final 后也开启新解码状态。

`build_app` 绑定路由；`main` 解析模型、显存、chunk、unfixed 与 committed-prefix 参数并启动 uvicorn。每请求 asr_commit JSON 日志包含 session_id、segment_index、is_final、audio_samples、raw/committed token ids、raw/visible text、first_conflict_index、stalled。正常请求 INFO，冲突 WARNING。

## 修复原因与验证边界

2026-10-15 的旧实现把 final 全文锁入 committed_ids 后继续复用已结束解码器，产生暂停恢复后多秒可见文本空档。仅由字符串改 token 比较不能消除这个问题。当前 duplex VAD pause 已能触发 ASR flush，旧文档“没有发布者”的说明已过期。历史证据见 [诊断](../../fdb_latency_diagnosis.md)。

当前修复隔离了 final 前后的解码状态，但失去跨段声学上下文；词尾丢失、重复、英文空格及真实识别准确率必须在远端用 Candor 暂停续说验证。假模型单测只能验证状态生命周期与累计前缀契约。
