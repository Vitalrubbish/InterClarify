# 英文组件远端单卡作业

无类。脚本显式选择 asr 或 tts，在调度分配的单卡启动对应独立服务；核验 source.sha256，保存设备、资源采样和日志，等待真实预热 readiness，再执行 verify_english_components。EXIT trap 关闭进程组并写退出码；输出已存在则拒绝覆盖。具体输入与资源见 docs/issue/002_003_remote_execution.md。该入口不启动LLM、不执行FDB、不做候选比较。


资源与来源补充：health记录加载耗时和进程峰值RSS，作业收尾保留service /proc状态，GPU逐秒采样；ASR关闭记录等待worker释放耗时。采集manifest标为integration_diagnostic_only且禁止训练，保留源音频摘要与失败。TTS核验增加真实Kokoro经RuntimeAdapter、TTSManager、协调器和播放管理器执行短附和、有效插话停旧音频及新响应，headless确认不等同扬声器实播。
