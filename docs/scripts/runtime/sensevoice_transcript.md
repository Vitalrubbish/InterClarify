# SenseVoice 原始正文与窗口整理

对应 `scripts/runtime/sensevoice_transcript.py`。`SenseVoiceObservation.parse()` 从原始识别串分离已知语言、情绪、声音和ITN标签，保留原始串、标签顺序及正文字符映射；未知标签明确标记，不当作控制状态。数字、标点、大小写和附和不经过SoulX控制归一化。

`TurnTranscriptAssembler` 只保存当前话轮可重建全文与活动尾部边界，不再维护正文版本或修订patch。`apply_window()` 支持同起点重新识别替换、滑窗唯一词锚点接续，以及reset后的严格相邻片段拼合；允许增加、删除或修改旧词。无法确定锚点或音频范围不连续时保留最后正文并标记gap。

空识别不抹掉已有正文；异常标记覆盖缺口。`apply_turn_result()` 沿用相同拼合规则，不凭“整段识别”绕过真实音频来源校验。正文最多65536字符，触限失败。

窗口正文不能直接当作话轮全文覆盖，也不能无条件累加`asr_segment`。整理结果先留在前端，待本块状态及完成分支处理结束后，联合写入SharedContext。既有样本仍可能有拼合gap，成功写入不代表转写准确或完整覆盖音频。
