# Issue 004 远端数据执行任务单

状态：进行中（正式构建作业已提交，实际产物与人审待完成）。父任务：[004](004_training_data_and_annotation.md)。本任务单只执行 CPU 数据构建，不启动训练或模型服务。

当前run_id为issue004-build-r3，冻结源码ae02d60，在调试机固定1CPU/nice10/2GiB地址空间硬限下直接执行，外层3600秒、数据目录10GiB、0GPU。只读取固定种子跨shard窗口中最多6000条原始对话，再过滤、候选分组、1000/200/300切分、三视图及机器审计和材料导出。旧r1/r2全库作业已停止并保留记录；不再要求全库对话过滤。每1000已抽取对话写build.log。详见[018](018_layer1_data_delivery.md)。

诊断/下载恢复作业 `job-179239520300088615232-xuan-zhang`（r4，源码5df0ef0）已完成：23项测试、32条诊断及10文件下载验真均通过，最终退出0。后续source/dfd36d3独立复核全部SHA256通过。原失败/撤销记录保留。来源隔离登记已完成，用户取消FDB补转写条件，下一步可准备正式分组切分和数据审计。

按用户明确要求，轻量单元测试/32条检查可在远端调试机按1CPU、2GiB地址空间硬限和超时执行；[实测](../../reports/layer1_training/issue004-debug-probe-20261019/README.md)为6.894秒、约149.94MiB峰值RSS。以下调度与32GiB申请约束仍用于完整全库构建，不用于要求同规模轻量检查排队。排除清单已在scope-correction-r2按新规则重建，reviewed=true、review_scope=source_inventory_and_available_text；可选FDB文本覆盖不完整不阻塞此任务。

## 前置核对

1. 经 GitHub 同步已提交源码，冻结 checkout 和逐文件摘要，工作目录遵循 [远端约定](../remote_workspace.md)。
2. 核实来源下载作业退出码，十个 shard 大小/SHA256 齐全，不能使用中断的 .part；独立训练 conda prefix 中 import tokenizers/yaml/sqlite3 通过。
3. 准备外部排除 JSON 清单，登记 FDB/FLEURS/历史五例检查来源与边界；正式数据交付前完成审查，不伪造 reviewed=true。
4. 有限6000样本在调试机按上述1CPU/2GiB硬限串行执行，构建1800秒、审计900秒、审查材料300秒，总3600秒；有效配置将目录预算设10GiB、保留5GiB余量。仅一个生成实例。规模不足/超限如实失败，不退回全库扫描，不并发重复运行。

## 执行命令

以下路径是已登记资产，提交前核对其实际存在；`LAYER1_EXCLUSIONS` 须由前置审查生成。4096 仅作首次数据信息审计长度，005 实测后重建/冻结实际训练长度。

```bash
export LAYER1_DATA_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/InterClarify
export LAYER1_TRAINING_ENV=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/envs/training
export LAYER1_SOURCE_DIR=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/ultrachat
export LAYER1_SOURCE_MANIFEST="$LAYER1_DATA_ROOT/reports/layer1_training/issue001-inventory-20261018/data_source_manifest.json"
export LAYER1_TOKENIZER=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28/tokenizer
export LAYER1_EXCLUSIONS=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/manifests/exclusions.json
export LAYER1_DATA_OUTPUT=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue004-build-r1
export LAYER1_DATA_MAX_LENGTH=4096
bash "$LAYER1_DATA_ROOT/scripts/remote/run_layer1_data.sh"
```

在调度器作业命令中设置上述变量后运行，不能仅在提交 shell 设置而丢失到计算节点；实际 vc 提交参数沿用已验证 CPU 作业模板并记录 job ID。先做小配置验证入口，再完整 1000/200/300。小配置通过不能交付为完整规模。

## 回收与验收

回收 source/environment/exit_code、build/audit 日志、完整 manifest 和审计统计，不提交全部原文和序列。导出review/minimum_32.md、expanded_samples.md、selection.json及human_review_template.json。最小32条全部人工审查；从已生成数据按6类行为每类20事件抽查，train/dev/test为12/4/4，每类4事件安排独立双人复核。这是对正式数据的抽查，不扩大训练集。模板签署留空，实际人工完成后回填dataset/human_review.json并重跑审计。逐项回填004，005最小集移交明确实际长度；规模不齐、人审未完成或审计失败均不放行006。
