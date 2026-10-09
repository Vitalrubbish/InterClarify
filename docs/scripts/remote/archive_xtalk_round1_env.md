# `scripts/remote/archive_xtalk_round1_env.sh`

## 整体作用

归档首轮验收的环境与来源证据到 `$XTALK_ROUND1_ARTIFACT_ROOT/env/`：conda 环境（镜像 base 与四个 `xtalk-round1-*`）的 pip freeze 与 conda explicit 列表、解析后的 `models.lock.json`、四份源码的固定提交。供任务单第 7 节回传使用。

## 核心步骤

- 对 `xtalk-round1-tools/asr/moss/client` 四个环境分别写 `*.pip.txt` 与 `*.conda.txt`，记录安装后的真实版本（依赖候选尚未冻结，以实测为准）；`base` 环境用于 LLM 与 turn detector，另单独归档。
- 复制模型锁定文件；逐个输出源码仓库的当前 HEAD 到 `source_commits.txt`。

GPU 与驱动信息必须在计算节点采集，由 `run_xtalk_round1_node_job.sh` 负责，不在本脚本范围内。
