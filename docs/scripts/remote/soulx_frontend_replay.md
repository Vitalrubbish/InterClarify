# 真实音频到 SharedContext 的回放检查

对应 `scripts/remote/soulx_frontend_replay.py`。`prepare_manifest()` 在轻量 CPU 阶段冻结既有 FLEURS 开发录音摘要、参考文本、完整／截断／重复／静音视图和资源边界。仅一个开发说话来源，派生视图不是独立音频样本集，不属于 benchmark。

`main()` 校验并复用冻结加载器，在调度 GPU 和既有 conda 中加载模型；三块静音预热后逐样本重新 reset。`replay_case()` 用独立接收线程按80ms真实时间送包，一个模型在途，800ms积压触限失败；合成尾部标记来源，EOF不补造完成状态。

`CaseAudit` 在前端发布前保存原始来源，在提交后让两个独立 `FrontendConsumer` 读取，逐项核对原始generate文本、标签跨度、正文patch、五状态及依据、关闭文本。文件分别保留来源审核和消费者实际读取。停止回调使用输出替身，只检查投递，不宣称真实停播。

输出 `progress.json`、`result.json`、每例事件／来源记录与模型配置；报告状态计数、缺口、在线版本、消费者一致性和发布延迟。`passed` 表示回放及写入完整性成功，拼合缺口、识别误差和未覆盖状态仍须单独披露，不能以退出码证明全面质量达标。
