# 原生控制协议契约检查

对应`tests/test_native_soulx.py`。official_model从冻结官方源码提取实际方法，使用微型CPU张量和确定性LLM／ASR依赖替代大权重，真实执行process、infer、ASR、状态预测、服务和reset逻辑。

NativeTests将同PCM、种子与配置的未插桩调用与封装对照，比较音频窗口、识别输入、LLM输入和KV次序、文字修订、规则、反馈、服务结果及reset随机缓冲。额外检查主块／前瞻来源、reset后未读PCM、远场与无语音拒绝、wait_fallback不冒充complete、nonidle只暂存且不存在前端停止钩子，以及取消后拒绝调用。

NTF-017撤销此前“停止先于状态交付”的断言；状态与正文共同可见由[双路检查](test_independent_frontend.md)验证。测试不证明真实模型质量或GPU性能，远端验证仍属018／019。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_native_soulx.py -v`。
