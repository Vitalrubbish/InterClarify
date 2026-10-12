# test_duplex_model_service.py

## 功能、类与核心方法

DuplexModelServiceTests 使用 FakeModel 与 FastAPI TestClient 检查实际 wire token、stop 原因、health 模型信息、raw ChatML 输入与预算校验。test_checkpoint_validation 验证严格权重键检查，避免服务带有随机初始化层。测试不加载模型；真实权重与 GPU 推理需远端任务验证。

新增发布 q/v 基础权重键迁移测试，验证原张量不变、键名完整覆盖、映射冲突与未知键拒绝。
