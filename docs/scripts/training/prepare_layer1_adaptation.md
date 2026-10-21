# 延迟启动配置校验

078增加`validate_asr_config`分支，通过新协议独立核验用户本次1k训练授权、新ASR机器审计/重建摘要、60条代理阅读登记、完整ASR索引与原切分身份；步数、warmup及保存间隔从新索引计算，优化器其余参数严格沿用040。`validate_index`按协议的arm选择T2或ASR，不允许错用视图；旧040授权、配置与资源约束保持原值。

`scripts/training/prepare_layer1_adaptation.py`是无CLI的校验模块，不加载模型、不生成计划或提交作业。`release_blockers`检查父协议的训练放行、已通过门禁和最终epoch选择；`validate_index`校验登记T2或ASR索引的对话集合、窗口、序列数、监督token与步数；`validate_delayed_config`按协议分支比对冻结参数、用户直接训练授权、数据audit、完整索引摘要和资源预算。

`EXPECTED_DELAYED_CONFIG` 固化 T2_R3 的种子、warmup、保存间隔、加权 loss 和控制权重，避免训练入口被配置覆盖绕过。校验通过后返回父协议与延迟训练字段的合并视图，供训练器登记训练后评价条件。旧 006 四配置计划、036 对齐配置及其校验函数已随旧设计删除。
