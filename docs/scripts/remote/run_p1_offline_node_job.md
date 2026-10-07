# `scripts/remote/run_p1_offline_node_job.sh`

## 作用

P1.1 离线样例的容器内入口：在 GPU 节点上运行 `scripts/run_p1_offline_sample.py`，输出写入共享存储。

## 关键行为

- 环境变量：`INTERCLARIFY_ROOT`、`INTERCLARIFY_MODEL_ROOT`、`INTERCLARIFY_ARTIFACT_ROOT`、`IC_PYTHON`、`IC_SCRIPT`；
- 设置 `PYTHONPATH=$REPO_ROOT/src`，并置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，因为权重与 tokenizer 全部是本地文件，禁止任何网络访问；
- `IC_SCRIPT` 非空时作为 `--script` 传入（JSON 文件路径）；
- 日志写 `logs_submit/node.<UTC>.log`，脚本 rc 透传。
