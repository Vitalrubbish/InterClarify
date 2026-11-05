# 原生SoulX冻结配置

对应配置：`configs/native_soulx.json`，工作单NTF-015。固定官方源码提交`a0b9063843df69619b087b95b74597b2176910b8`及21份Python摘要；SoulX权重revision为`61701c4ab8193cc1ee2220d3848872ac6c720142`，SenseVoice为`3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`。

`runtime_config`基于官方YAML，仅选择已有英文SenseVoice教师；保留seed=42、BF16配置、等待8、误判3、远场阈值0.02、2560主块、15360回看与640前瞻。模型配置与权重不变。

2026-11-05，NTF-052／053新增`execution_config`：cpu_threads=2、interop_threads=1、skip_complete_recognition=true。加载器显式传递SenseVoice ncpu并核对实际值；观察适配器按[执行修订](../dev/SoulX-Duplug/runtime_execution_update.md)跳过complete后的整段识别。该执行策略与固定官方完整服务行为有明确差异，不能继续把新路径称为完整服务输出严格等价；旧报告与旧配置摘要保持历史含义。

`soulx_files`冻结16份实际模型／词表／配置文件，`sensevoice_files`冻结5份模型／前处理文件。摘要来源是2026-10-28既有下载验收清单，本次通过只读SFTP取得该JSON并记录其完整SHA256，避免终端换行影响摘要。此次没有在登录节点重新扫描大权重；运行时加载器会重新逐文件核验，缺失或变化立即退出。

X2继续独立使用[x2_streaming_probe配置](x2_streaming_probe.md)，不将X2加入SoulX教师配置。真实权重加载与对照验证属于NTF-018／019。
