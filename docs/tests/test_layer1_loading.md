# 完整加载与零更新测试

`tests/test_layer1_loading.py`用unittest检查strict键/shape、映射不丢张量、碰撞拒绝、每层已有q/v default LoRA精确白名单、embedding/head冻结、资产篡改拒收和既有prompt取样。`Tensor/Wrapper`替身不加载模型；`LoadingTests`负责不依赖torch的契约测试。

`TensorLoadingTests`在有torch/safetensors的远端conda执行真实小张量散列和全词表比较，验证冻结参数变化、超容忍logits或生成ID变化都会失败；本地缺依赖时明确跳过，不冒充运行。实际7B加载/推理只在单卡作业进行。
