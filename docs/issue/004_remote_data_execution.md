# Issue 004 远端数据执行任务单

状态：待办。父任务：[004](004_training_data_and_annotation.md)。本任务单只执行 CPU 数据构建，不启动训练或模型服务。

## 前置核对

1. 经 GitHub 同步已提交源码，冻结 checkout 和逐文件摘要，工作目录遵循 [远端约定](../remote_workspace.md)。
2. 核实来源下载作业退出码，十个 shard 大小/SHA256 齐全，不能使用中断的 .part；独立训练 conda prefix 中 import tokenizers/yaml/sqlite3 通过。
3. 准备外部排除 JSON 清单，登记 FDB/FLEURS/历史五例检查来源与边界；正式数据交付前完成审查，不伪造 reviewed=true。
4. 申请单个 4 CPU/32GiB/0GPU 作业；不在登录节点生成全库。原始源约 10GB，索引/生成另限 100GiB，保留至少 5GiB 可用空间；最多一个生成作业。超过 4 小时建库或 1 小时审计退出，依据实测登记调整，不并发重提。

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

回收 source/environment/exit_code、build/audit 日志、完整 manifest 和审计统计，不提交全部原文和序列。最小 32 条全部人工审查；完整集按行为类别抽查并对部分样本双人复核，保存审查与产物摘要的对应。逐项回填 004，005 最小集移交明确其实际长度。来源未验真、规模不齐、人审未完成或审计失败均不放行 006。
