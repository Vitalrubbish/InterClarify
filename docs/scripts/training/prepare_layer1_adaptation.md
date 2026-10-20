# 延迟启动配置校验

`scripts/training/prepare_layer1_adaptation.py` 是无 CLI 的校验模块，不加载模型、不生成计划或提交作业。`release_blockers` 检查父协议的训练放行、已通过门禁和最终 epoch 选择；`validate_index` 只校验最终 T2 索引的对话集合、窗口、序列数、监督 token 与步数；`validate_delayed_config` 比对当前 `configs/layer1_delayed_training.yaml` 的冻结参数、用户直接训练授权、数据 audit、完整索引摘要和资源预算。

`EXPECTED_DELAYED_CONFIG` 固化 T2_R3 的种子、warmup、保存间隔、加权 loss 和控制权重，避免训练入口被配置覆盖绕过。校验通过后返回父协议与延迟训练字段的合并视图，供训练器登记训练后评价条件。旧 006 四配置计划、036 对齐配置及其校验函数已随旧设计删除。
