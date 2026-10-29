# 通用前端 SharedContext

对应 `scripts/runtime/shared_context.py`。独立于 TextTurn 的历史实现，保存来源观察、控制视图、正文、五状态和生命周期，提供统一有序事件流与话轮视图。内存存储不承诺进程重启后持久化。

`SharedContext.commit_frontend_events()` 在短锁内先校验完整事务，再一起提交；以稳定事件 ID 去重，以 producer ID 和序号检查缺口。校验依赖、正文 patch 重建、ASR 版本、关闭及控制器 generation，错误不会留下半个事务。正文支持替换，不限制前缀追加。

`get_user_turn()` 返回当前正文、最新状态与保留完整性；可在已保留水位查询历史。`read_frontend_updates()` 按统一游标读取，`read_user_transcript_updates()` 仅过滤正文。各 `FrontendConsumer` 单独保存游标，正文替换同一 turn 的视图。重同步只恢复正文，不重放历史控制动作。

事件环默认最多4096条／16MiB，单条256KiB、正文65536字符、话轮128个。过期游标抛出 `CursorGap`，最新视图明确标记来源引用是否已回收；`release_closed_turn()` 只允许主动释放已关闭话轮。状态历史以事件流为准，最新视图只保留最新观察，防止重复保存大载荷。

本地契约检查见[测试说明](../../tests/test_shared_context.md)；设计与真实音频结果分别见[前端设计](../../dev/SoulX-Duplug/asr_frontend_design.md)及对应实验报告。
