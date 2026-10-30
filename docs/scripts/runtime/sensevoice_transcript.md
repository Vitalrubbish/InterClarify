# SenseVoice 增量草稿与整段覆盖

对应 `scripts/runtime/sensevoice_transcript.py`。`SenseVoiceObservation.parse()` 从原始识别串分离已知语言、情绪、声音和ITN标签，保留原始串、标签顺序及正文字符映射；未知标签明确标记，不当作控制状态。数字、标点、大小写和附和不经过SoulX控制归一化。

`TurnTranscriptAssembler`只保存此前controller片段的当前文字和当前活动草稿，不维护正文版本或修订patch。`apply_deltas()`从原生`past_state['delta_text']`列表重建草稿，包含上一周期替换、删除和空增量；英文片段按词间空格连接，中文片段直接连接。

`apply_turn_result()`将分离标签后的成功整段结果替换活动草稿，保留标点、数字、大小写和原有空格。它按generation定位，不再使用窗口词锚点；无真实音频、普通空返回不清空草稿，识别错误、未知标签或跨generation／不连续音频标记缺口。成功整段识别可清除当前片段缺口，不能修复以前片段已知缺口。正文最多65536字符，触限前保持原值。

`begin_generation()`在controller reset时保留全文作为前文，开始新的内部片段；新片段的整段结果不能覆盖前文。逻辑用户话轮不因此关闭。`note_failure()`仅标记缺口并保留当前文字。

原始窗口结果仅用于诊断，草稿接受原生控制文字的规范化；完成与等待兜底分支复用已有整段识别，不新增模型调用。整理结果仍在160ms处理结束后与本块状态联合覆盖SharedContext。覆盖标志不证明转写准确或所有用户发声已识别。
