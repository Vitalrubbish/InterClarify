# Issue 017：完整训练加载与独立零更新对照

状态：进行中（r1入口失败，审查决定暂不关闭）。日期：2026-10-19。父任务：[005](005_training_runtime_and_resource_probe.md)。本工作只推进权重恢复、更新白名单和零更新对照，不实现优化器训练循环、不启动006。

- [x] 提取完整模型恢复与键迁移到layer1_model.py，推理服务复用；6项远端HTTP/历史/ID契约回归通过，实际GPU逐拍回归仍待。
- [ ] 发布资产逐文件验摘要、strict恢复、shape/映射审计；所有embedding/head必须恢复，训练只开放已有q/v LoRA A/B。
- [x] 固定001的15个历史prompt、BF16/64-token贪心、logits atol=0.02/rtol=0.01和生成IDs完全一致，入口在比较前物化配置/fixture。
- [x] 实现独立官方model.py参考路径和strict键/shape映射，两套模型单卡干净进程串行加载；真实模型验收另列。
- [ ] 实际对比每个生成步完整词表raw logits与IDs，检查无更新前后权重摘要和trainable白名单；失败不放行训练。
- [ ] 本地替身/CPU小模型验证，远端1×4090真权重对照与受影响服务回归；交付同路径中文说明与原始报告。

资源：不在调试机加载7B权重；GPU作业最多1个、1张24GiB 4090，实际8CPU/32GiB主存，零更新1800秒、成功后001回归另600秒，总上限2400秒，输出上限5GiB。初始64GiB申请因单GPU最多32GiB规则被拒绝，先下调并实测，不以增加GPU申请规避；来源下载现已退出，不与新任务重复运行。005资源短跑、梯度更新及训练状态恢复仍由父任务后续验收。

远端轻量验证：7项加载测试（包括2项真torch/safetensors小张量测试）全部通过，约4.4秒、峰值约418MiB，无GPU。补齐独立训练prefix的固定HTTP测试依赖后，6项服务测试全部通过，约1.97秒、峰值45,360KiB；torch/transformers/peft及已有h11/anyio版本未变。单卡作业job-179239981090839983547-xuan-zhang于2026-10-19 20:52:02（+08:00）在d6-hpc-gpu-053启动后立即退出2；源码dfd36d3，计划输出issue017-zero-update-r1未创建。集群设置NVIDIA_VISIBLE_DEVICES，而入口只接受CUDA_VISIBLE_DEVICES，触发An allocated GPU is required。真权重验摘要、零更新和后续136拍回归均未执行，不得勾选通过。结果和原件见[实施记录](../../reports/layer1_training/issue017-loading-20261019/README.md)。

## 结果审查与后续条件

2026-10-19已通过SSH回收原始日志、调度器生成入口和vc describe记录，见[审查报告](../../reports/layer1_training/issue017-loading-20261019/README.md#2026-10-19-远端结果审查与关闭决策)。决策：**不关闭、不归档**；7项加载及6项HTTP测试不能替代缺失的真权重证据。本次未启动新作业。

- [ ] 先更新入口说明，再修正GPU分配检查以兼容容器环境，并记录检查失败退出证据；实际CUDA单卡验证仍须在受调度作业内进行。
- [ ] 在原定资源预算内使用新run_id重跑零更新；成功后串行执行五例136拍回归，回收审计和对照报告后重新决策关闭。
