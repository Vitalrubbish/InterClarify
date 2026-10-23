# XTurnix 协议配置测试

`tests/test_xturnix_protocol_probe.py` 只验证协议配置的冻结约束，不加载模型、不启动服务、不读取音频。

覆盖内容：

- 仓库中的 `configs/xturnix_fleurs_test.json` 可被探针加载，并保持 160ms 模型分块、80ms 传输、Listen 双动作和 2048 上下文；
- 未知 schema 被拒绝；
- 启用 pause 注入被拒绝；
- 修改传输包长或允许两个在途控制请求被拒绝。

这些检查用于防止后续改动把正式协议静默改宽；模型行为、音频时序和资源峰值由远端 dev 探针验证，不由单元测试冒充。
