# `src/interclarify/config.py`

## 作用

统一配置层，落实 [engineering_implementation.md](../../engineering_implementation.md) 第 4.2 节第 4 项与第 4.3 节：把“本地开发 / 离线回放 / 集群实验”三类环境的差异集中到 `configs/`，代码只读取合并后的结果。配置同时被运行清单引用其摘要（digest），保证“同一次运行的配置可追溯”。

## 配置合并顺序

1. `configs/base.yaml`：共享默认值，并登记 DuplexCascade 仓库提交、权重修订和服务端点；
2. `configs/<profile>.yaml`：`local` / `replay` / `cluster` 之一；
3. 运行时 `overrides`：调用方显式覆盖。

合并为递归字典合并：同名字典向下合并，标量与列表整体替换。

## 主要函数

- `load_config(profile, config_dir, overrides, expand_env)`：加载并合并配置；`profile` 非法时抛 `ValueError`；`expand_env=True` 时展开字符串中的 `${VAR}` 与 `${VAR:-default}`。
- `canonical_json(cfg)` / `config_digest(cfg)`：以稳定排序的紧凑 JSON 计算 SHA-256，作为配置指纹。
- `write_resolved_config(cfg, path)`：把解析后的配置写为 YAML（即运行目录中的 `resolved_config.yaml`）。
- `resolve_paths(cfg, repo_root)`：解析 `paths.*`；相对路径以 `paths.repo_root` 为基准，使集群 profile 可指向共享存储绝对路径。

## 关键约束

- 环境变量展开只用于把机器相关根目录和密钥留在环境里，模板本身可安全提交；
- `cluster.yaml` 通过 `${INTERCLARIFY_ROOT:-...}` 等形式提供可用默认值；
- 配置不含隐藏任务真值或未来输入，符合在线可见性边界。
