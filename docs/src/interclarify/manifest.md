# `src/interclarify/manifest.py`

## 作用

实现 [engineering_implementation.md](../../engineering_implementation.md) 第 2.4 节与第 12 节的“实验清单”格式：每次运行用唯一 `run_id`，并记录可从何处复现——代码提交、配置摘要、底座与模型修订、随机种子、设备、起止时间与输出目录。清单只记录**来源信息**，不写入隐藏任务真值，可安全与在线日志并存。

## 主要数据类与函数

- `RunManifest`（dataclass）：字段包括 `run_id`、`profile`、`config_digest`、`seed`、`device`、`output_dir`、`repo_root`、`git_commit`、`git_dirty`、`git_branch`、`model`、`environment`、`started_at`、`finished_at`、`tags`、`extra`；方法 `mark_started` / `mark_finished` / `duration_seconds` / `to_dict`。
- `new_run_id(prefix)`：生成形如 `ic-20261007T153000-1a2b3c4d` 的可排序唯一 id。
- `collect_git_info(repo_root)`：返回提交、分叉和脏工作树标记。
- `collect_environment(cfg)`：采集主机、解释器、conda 环境、`CUDA_VISIBLE_DEVICES`、torch/CUDA 设备信息。
- `build_manifest(cfg, output_dir, repo_root, run_id, tags)`：组合出 `RunManifest`。
- `write_manifest` / `write_environment`：落盘 `manifest.json` 与 `environment.txt`。
- `manifest_fingerprint(manifest)`：对清单的“可复现子集”（剔除 `run_id`、时间、输出目录）求哈希，供测试与回归比较。

## 关键约束

- `model` 字段从配置的 `xtalk` 段复制，登记仓库提交、基础镜像和后续固定的组件信息（见 [../../p0/xtalk_registry.md](../../p0/xtalk_registry.md)）；
- 时间字段一律使用带时区的 UTC ISO 8601；
- Git 调用失败时字段为 `null`，不抛异常，保证无 Git 环境仍可运行。
