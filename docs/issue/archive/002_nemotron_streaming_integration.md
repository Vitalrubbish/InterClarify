# Issue 002：接入 Nemotron EN 160ms 并采集真实轨迹

状态：完成，2026-10-18。优先级：P0。依赖：001；用户授权接入准备与实现继续推进，001 未通过不放行 006。

## 目标

通过 X-Talk 原有 ASR 扩展点接入固定英文模型，为训练与评测提供真实在线前缀。保留 160ms 模型分块，音频传输粒度单独配置，不新增第二套运行时。

## 工作项

- [x] 在独立 conda 环境锁定官方推理依赖、权重、精度与模型配置，核验支持的连续流接口。
- [x] 在 X-Talk fork 实现通用客户端；必要的独立服务及部署配置放本仓库。拟新增 `scripts/remote/nemotron_asr_service.py`、`setup_nemotron_asr_env.sh` 和对应 docs，名称可在实现前按接口核验调整。
- [x] 按 session/stream generation 隔离增量、取消与 reset，验证 raw/visible 文本及词内增量，不无声回写已交付前缀。
- [x] 支持无新增音频时独立接收输出；暂停不关闭流；有限文件 EOF 排空尾词并结束识别，EOF 不进入 LLM 让轮判断。
- [x] 预热覆盖真实首会话与顺序会话；readiness 需证明模型加载、真实输出与清理完成。
- [x] 保存音频发送时刻、到达时刻、raw/visible 增量、前缀版本、终止原因和输入哈希；采集过程不读取未来边界。
- [x] 新增显式 Nemotron 运行配置和后端分支，旧 X2 配置继续标为诊断，禁止静默回退。

## 远端测试与完成条件

- [x] 正常、长停顿恢复、同会话多轮、两会话串行、取消后重连、EOF 尾词场景全部有原始日志和退出码。
- [x] 核对可见文本单调、末次输出未丢失、无跨会话/代际污染；发现回写时阻断交付并明确记录，不靠冻结前缀掩盖停滞。
- [x] 记录冷启动、输入时钟迟到、队列增长、首字/逐词交付覆盖和 GPU/CPU 峰值；复核历史 EN 预热失败与长尾是否复现，不预判归因。
- [x] 交付可供 004 使用的真实时间线及采集 manifest，保持数据集用途隔离。

远端资源先按单张 4090 申请并由短跑校验；仅转写/采集阶段不启动 LLM 或 TTS。新服务的类、核心方法及生命周期同步同路径说明。


## 完成回填

代码入口为 nemotron_asr_service.py、setup_english_component_envs.sh、verify_english_components.py 及X-Talk的NemotronStreamingClient。采用已测Transformers原生RNNT，不新增NeMo运行时，FP32/160ms保持。r4-asr作业 `job-179233016243237430568-xuan-zhang` 退出0；源码v6及包版本、模型摘要、逐例发送/前缀/EOF、采集manifest与资源均见 `reports/english_integration/20261018-r4/`，大日志留远端。

真实两次预热及正常、三秒停顿恢复、同流两轮、串行会话、短尾EOF、取消重连通过。五个完整场景最后轮询文本均等于EOF结果；构造停顿例识别出answers而非chances，保留质量差异，不声称任务WER达标。首字约1.00–1.38秒，发送最大迟到约4.54ms，GPU采样峰值2906MiB，CPU峰值RSS2514592KiB。逐词覆盖以最终识别文本为参考，不是人工逐词边界延迟；未执行真实任务域泛化评测。

采集用途固定为integration_diagnostic_only、禁止训练，真实音频与构造重复/静音分别标记。独立真实语音迁移评测仍属007；001未完全通过不放行006。首次两次WAV读取失败见归档002a，不归因模型预热故障。提交以本轮维护提交及source.sha256定位。


本轮实现提交：InterClarify `d23f80f`，X-Talk `f1531f3`；运行仍以各自run manifest的原始源码摘要为准。
