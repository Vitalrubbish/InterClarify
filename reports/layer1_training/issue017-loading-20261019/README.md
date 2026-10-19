# 训练加载与零更新实施进度

源码dc0cc7b实现公共完整恢复、shape/key审计、现有q/v default LoRA精确白名单、独立官方Model参考及零更新入口；dfd36d3将单GPU主存申请调整到实际配额32GiB。源码和测试说明位于docs同路径。训练器optimizer/梯度/RNG恢复尚未实现，本报告不宣称005完成。

## 验证范围

本地相关回归44项中40通过、4项按条件跳过，另6项既有服务测试通过；2项真张量测试的本地跳过由远端补齐。远端独立训练conda上已运行全部[7项加载测试](loading_tests.txt)，包括权重摘要变化和全词表容忍检查，退出0、约4.4秒。调试机绑定1CPU、nice10、8GiB地址空间上限、60秒CPU/90秒墙钟限制，峰值约418MiB，无GPU。源记录见[cpu_contract.json](cpu_contract.json)，该次service导入失败保留，不计入通过。

该远端环境缺httpx，首次服务测试在导入时失败，原件保留在issue017-cpu-contract-r1。通过conda base可用pip的--python参数，仅向独立训练prefix补httpx0.27.2/httpcore1.0.9/sniffio1.3.1，[安装日志](test_dependency_install.txt)和[最终版本](dependency_versions.json)齐全，torch/transformers/peft与既有h11/anyio保持原值。重新受限执行的[6项服务测试](service_tests.txt)全部通过，退出0、约1.97秒、峰值45,360KiB，见[资源记录](service_contract.json)。

## 真权重任务

单卡任务job-179239981090839983547-xuan-zhang，输出训练根data/runs/issue017-zero-update-r1，源码dfd36d3，申请8CPU/32GiB/1×4090。先运行加载/HTTP回归，再逐文件核对冻结资产，然后在两个干净子进程串行构建官方参考与候选训练加载。

固定001的15个prompt，长度为12/234/494、13/209/469、10/188/448、10/232/492、11/217/423 token，分别对应五例首/中/末请求。每prompt最多64个生成token，BF16 eval贪心；每步保存完整词表raw logits，按atol0.02/rtol0.01比较，生成ID须完全一致；实际恢复后的全参数摘要两路径一致，且零更新前后不变。白名单保留每层q/v LoRA A/B，embedding/head冻结。

通过后同一GPU顺序运行001原生Word的五例136拍回归，复用冻结X-Talk源码快照，检验公共加载重构没有改变实际服务行为。零更新1800秒、回归另600秒，总预算上限2400秒。首次64GiB申请被配额拒绝，未启动；修正后32GiB作业已提交，最新状态Pending，尚无真权重结果，不计通过。

完整资产、logits和权重摘要留远端，仓库只回收紧凑报告和原件摘要；训练放行保持false。后续仍需004正式数据/人审、005梯度与恢复短跑和007开训前准备。
