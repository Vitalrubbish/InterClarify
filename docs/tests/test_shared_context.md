# SharedContext 当前值检查

对应 `tests/test_shared_context.py`。CPU场景使用真实SharedContext验证：更正与删除直接覆盖、读者副本隔离及无历史存储；错误帧／倒退音频／关闭与容量边界不破坏当前值；并发读取不会混合不同帧的正文和状态。新增 Nemotron 显式开轮检查，验证固定来源及拒绝中途混入 SenseVoice。服务字段用例验证开轮默认值、`wait_fallback`携带、`model_complete`／`no_speech`组合校验及失败不覆盖当前值。

使用既有conda运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p 'test_shared_context.py' -v`。不加载模型，不将存储正确性当作识别质量。

NTF-012新增X2来源的开轮、原子发布与来源不可变校验；状态规则与限额不变。

NTF-017新增固定发布模式检查：X2默认joint，旧教师必须显式legacy_frame；帧字段不能切换模式，旧入口不能更新联合话轮。关闭元数据因容量失败时仍保留终止屏障，恢复容量后迟到写入仍被拒绝。联合事务、并发副本、交接元数据与失败无半帧的检查统一在test_independent_frontend.py。
