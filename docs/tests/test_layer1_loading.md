# 完整加载测试

`tests/test_layer1_loading.py`用unittest检查strict键/shape、映射不丢张量、碰撞拒绝、每层已有q/v default LoRA精确白名单、embedding/head冻结和资产篡改拒收。`Tensor/Wrapper`替身不加载模型；`LoadingTests`负责不依赖torch的契约测试。

`TensorLoadingTests`在有torch的远端conda执行真实小张量散列，验证冻结参数变化可被检出；本地缺依赖时明确跳过，不冒充运行。实际7B加载/推理只在单卡作业进行。原零更新专用的prompt物化与全词表logits比较用例已随017工具（`check_layer1_zero_update.py`）于2026-10-20旧路线清理移除，历史证据见固定Git提交。
