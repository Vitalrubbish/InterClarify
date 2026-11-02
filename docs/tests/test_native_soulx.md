# 原生控制协议契约检查

对应测试：`tests/test_native_soulx.py`。`official_model()`从固定官方源码提取实际方法，使用微型CPU张量、确定性LLM／ASR依赖替代大模型；官方`process/infer/_asr/_state_predict/state_predict/reset`逻辑真实执行。

`NativeTests`将同PCM、同种子与配置下的未插桩官方调用与封装对照，逐项比较音频窗口、实际ASR波形、LLM输入及KV次序、文字修订、规则后状态、反馈、服务结果和reset缓冲数值。额外检查主块／前瞻来源、reset后未读PCM、远场与无语音complete拒绝、wait_fallback不冒充complete、停止先于状态交付且每个output_id去重，以及取消后拒绝调用。

测试没有加载权重，不证明真实模型质量或GPU性能；真实权重轨迹对照仍须在NTF-018／019执行。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_native_soulx.py -v`。
