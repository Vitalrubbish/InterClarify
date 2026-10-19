# 训练加载与零更新审查记录

源码dc0cc7b实现公共完整恢复、shape/key审计、现有q/v default LoRA精确白名单、独立官方Model参考及零更新入口；dfd36d3将单GPU主存申请调整到实际配额32GiB。源码和测试说明位于docs同路径。训练器optimizer/梯度/RNG恢复尚未实现，本报告不宣称005完成。

## 验证范围

本地相关回归44项中40通过、4项按条件跳过，另6项既有服务测试通过；2项真张量测试的本地跳过由远端补齐。远端独立训练conda上已运行全部[7项加载测试](loading_tests.txt)，包括权重摘要变化和全词表容忍检查，退出0、约4.4秒。调试机绑定1CPU、nice10、8GiB地址空间上限、60秒CPU/90秒墙钟限制，峰值约418MiB，无GPU。源记录见[cpu_contract.json](cpu_contract.json)，该次service导入失败保留，不计入通过。

该远端环境缺httpx，首次服务测试在导入时失败，原件保留在issue017-cpu-contract-r1。通过conda base可用pip的--python参数，仅向独立训练prefix补httpx0.27.2/httpcore1.0.9/sniffio1.3.1，[安装日志](test_dependency_install.txt)和[最终版本](dependency_versions.json)齐全，torch/transformers/peft与既有h11/anyio保持原值。重新受限执行的[6项服务测试](service_tests.txt)全部通过，退出0、约1.97秒、峰值45,360KiB，见[资源记录](service_contract.json)。

## 真权重任务

单卡任务job-179239981090839983547-xuan-zhang，输出训练根data/runs/issue017-zero-update-r1，源码dfd36d3，申请8CPU/32GiB/1×4090。先运行加载/HTTP回归，再逐文件核对冻结资产，然后在两个干净子进程串行构建官方参考与候选训练加载。

固定001的15个prompt，长度为12/234/494、13/209/469、10/188/448、10/232/492、11/217/423 token，分别对应五例首/中/末请求。每prompt最多64个生成token，BF16 eval贪心；每步保存完整词表raw logits，按atol0.02/rtol0.01比较，生成ID须完全一致；实际恢复后的全参数摘要两路径一致，且零更新前后不变。白名单保留每层q/v LoRA A/B，embedding/head冻结。

通过后同一GPU顺序运行001原生Word的五例136拍回归，复用冻结X-Talk源码快照，检验公共加载重构没有改变实际服务行为。零更新1800秒、回归另600秒，总预算上限2400秒。首次64GiB申请被配额拒绝，未启动；32GiB作业已于2026-10-19 20:52:02（+08:00）启动并在同秒失败，退出2，未进入模型加载。

完整资产、logits和权重摘要留远端，仓库只回收紧凑报告和原件摘要；训练放行保持false。004已按r5机器审计及用户免除复审授权关闭；后续仍需017真权重验证、005梯度与恢复短跑和007开训前准备。

## 2026-10-19 远端结果审查与关闭决策

**不关闭017，保持进行中。** 本次取得的是入口失败证据，不能作为真权重验证通过。原始[作业输出](r1-review/job_output.txt)、[调度器描述](r1-review/job_describe.txt)、[调度器生成入口](r1-review/issue017-zero-update-r1.sh)及[回收摘要](r1-review/retrieval.json)已保存。

调度器记录phase=Failed、reason=Error、exitCode=2；节点d6-hpc-gpu-053，申请8CPU/32GiB/1GPU。容器环境包含NVIDIA_VISIBLE_DEVICES=GPU-7b57855a-1ee0-bc43-987c-3b381e85405d，未包含CUDA_VISIBLE_DEVICES。run_layer1_zero_update.sh在创建输出目录前要求CUDA_VISIBLE_DEVICES非空，因此报An allocated GPU is required并退出。这是GPU分配判定与集群容器环境不匹配，现有证据不支持归因于OOM、权重或logits差异。

回收时data/runs/issue017-zero-update-r1目录不存在；入口在该检查后才安装退出码trap，因此也没有产物exit_code.txt。后续136拍回归通过&&连接，未执行。旧的7项加载与6项HTTP测试结果仍有效，但本次GPU作业连这两组测试也未运行，不能重复计为新验证。调度器另报./path.sh不存在，但wrapper以echo容忍该错误并继续到GPU检查，直接终止原因仍为GPU检查。

| 验收项 | 当前证据 | 结论 |
| --- | --- | --- |
| 小张量加载与HTTP契约 | 既有远端7项、6项通过 | 已满足轻量验证 |
| 发布资产逐文件摘要与strict/shape映射 | 真权重入口未执行 | 未验收 |
| 15个prompt完整词表logits与生成IDs | 无comparison.json和模型输出 | 未验收 |
| 两路径全参数摘要、零更新前后摘要及LoRA白名单 | 无真权重审计产物 | 未验收 |
| 重构后的五例136拍真实服务回归 | 前置失败，未执行 | 未验收 |

重跑前需修正单卡入口的分配检查：兼容集群NVIDIA_VISIBLE_DEVICES，并在受调度的容器内用实际CUDA可用性、可见设备数量及显存确认单卡；不可仅删除检查后在调试机加载7B。还需在检查失败时留下可回收的退出证据。修正代码前同步对应中文说明，保持现有单GPU、8CPU/32GiB、总2400秒、输出5GiB上限，使用新run_id，保留r1原件。随后先零更新、成功后再136拍回归，全部满足才可关闭017；005及006训练放行仍为false。本次仅回收和审查，未修改实现或提交新GPU作业。
