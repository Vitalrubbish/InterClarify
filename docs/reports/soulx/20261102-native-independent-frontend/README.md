# NTF-015／016交付记录

日期：2026-11-02。范围：原生SoulX控制封装、同源PCM账本、160ms双路推进屏障及独立X2完整词适配。本次只完成本地实现与必要契约验收，没有启动远端真实模型作业；NTF-017原子Context、NTF-020交接与NTF-018／019真实权重、预热及实时性验收继续待实施。

## 实现与冻结

| 工作单 | 交付 | 说明 |
| --- | --- | --- |
| NTF-015 | [原生封装](../../../scripts/runtime/native_soulx.md) | 保留官方门控、窗口识别、归一化、KV修订、规则、反馈、整轮识别及reset；原始状态与外层服务分开；有效nonidle先停止后交付并按output_id去重 |
| NTF-015 | [离线加载器](../../../scripts/runtime/native_soulx_loader.md)、[冻结配置](../../../configs/native_soulx.md) | 独立调用官方TurnModel，核对源码、英文配置、SoulX及SenseVoice资产 |
| NTF-016 | [PCM与屏障](../../../scripts/runtime/dual_audio.md) | 连续16kHz单声道float32、单位增益、真实采样／padding分别记录，两路实际完成后才推进；生产者不等推理 |
| NTF-016 | [独立X2](../../../scripts/runtime/independent_x2.md) | 每80ms执行原生LISTEN／DECODE；EOS闭合后即时交正文，WAIT仍交进度，开放组最多64 token；不接受控制文字或complete/reset指令 |

官方SoulX源码固定`a0b9063843df69619b087b95b74597b2176910b8`，子模块保持干净，21份Python摘要进入配置。SoulX权重revision`61701c4ab8193cc1ee2220d3848872ac6c720142`，SenseVoice revision`3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`，分别冻结16份及5份资产摘要。

资产摘要来自已有下载验收JSON，只读复制后SHA256为`61415c9e35b65e71697ebc0c250996618edc2528e00e0929fd52cd9a829937f4`；不是本次重新扫描远端大权重所得。实际加载前逐文件重新计算，变化即失败。远端只读检查使用已有`envs/soulx` conda，不运行推理、创建模型副本或提交作业。

X2沿用既有`configs/x2_streaming_probe.json`：revision`4c8df16`，官方源码`0aca80597bb1399c0be4002de5bc62c0a779c542`，BF16、英文language-tag、80ms协议，权重SHA256`fadba62dde440bb7e31c011f2b85b3d3bc5d6b1a1c265ebc4f968c28b5bfe5c1`。只复用X2因果引擎和官方组拼接规则，文字发布由联合批次统一完成。

## 关键采样与生命周期决定

实施前先补充了[设计第2.2节](../../../dev/SoulX-Duplug/independent_streaming_frontend.md#22-ntf-015016采样映射与实现冻结)：官方startup／reset首主块含640合成采样及1920真实采样，真实前瞻为后续640；不能把本批次2560采样全记作已处理。reset仍清除内部KV／回看／padding，未消费真实PCM从外部账本重新供给，不写回旧buffer；因reset产生的控制滞后真实记录并受800ms限制。

同一160ms批次的两个80ms与控制调用允许串行，协调器默认一个调度worker；X2第一帧结果可以先于第二帧和控制发布。完成回执等待设备同步，带真实窗口、主块截止、观察截止、输入实际到达、调度开始、完成、等待及释放时间。内部reset不重置全局step_id；缺失、错误、重复、过期、取消回执均不能释放下一步。

传输包在复制前检查每路800ms与总PCM4MiB；模型拼接、切块副本、reset和X2窗口也预留分配预算。任一路失败立即终止本样本并保留两路进度、未完成屏障、原生状态／内部ASR与开放组诊断。取消与短回调串行，关闭后拒绝迟到发布；设备执行由worker收尾后才能detach。EOF只处理实际存在的终止帧并显式登记右padding，不补EOS、额外drain或将尾词诊断回填为在线正文。

## 本地验证与实际边界

本地使用已有`interclarify-dev` conda，新增检查见[原生对照](../../../tests/test_native_soulx.md)、[加载冻结](../../../tests/test_native_soulx_loader.md)及[双路适配](../../../tests/test_independent_frontend.md)。

完整回归命令`conda run -n interclarify-dev python -m unittest discover -s tests -q`实际通过134项、退出0，其中本次新增28项（原生5、加载器4、双路19）；没有跳过。新增运行模块和测试语法检查、Git差异空白检查及同路径说明完整性检查通过。

原生对照执行真实官方`process/infer/_asr/_state_predict/state_predict/reset`方法，以微型CPU张量及确定性依赖替代大权重；同PCM、种子与配置下，比较未插桩参考与封装的实际音频／文字／LLM输入、KV顺序、窗口修订、规则反馈、服务返回、reset随机缓冲及状态轨迹。其余检查覆盖两种完成顺序、下一周期不得抢跑、EOS多子词／多词组、连续WAIT、开放组EOF、前缀不可改、正文时间独立、reset后PCM及正文连续、实时生产者、800ms／4MiB、单路失败、关闭和过期回调。

真实依赖加载、同权重轨迹等价性、首块／增量实际形状、同卡实时性、识别质量、尾词退化与完整预热均未在本次验证，按既有工作单留给NTF-018／019。短回调尚未接入新的原子Context；原始complete回调不表示交接ready或准许正式回答。当前实现没有接入LLM／CoT／TTS或切换现役Agent。

## 归档

NTF-015／016的代码、配置、必要契约检查与同路径中文说明已交付。完成任务单移入本地`docs/issue/archive/`，按仓库约定不纳入Git；本报告保留可追踪交付范围，原工作单正文可由此前提交`c1e0cb7`追溯。后续活动工作单为017→020→018→019。

后续迁移：NTF-017已将本报告中的首帧提前发布与独立停止口径替换为160ms双路联合提交，本地全量144项通过，见[新交付](../20261102-ntf017-joint-publication/README.md)。本报告保留015／016当时实现和134项检查的历史事实，不作为新合同验收证据。

2026-11-03后续决定：用户取消并归档NTF-020，160ms联合提交后的有效complete不再等待独立pending／ready或专用超时；原文保留当时计划，当前合同见[归档记录](../20261103-ntf020-handoff-retirement/README.md)。
