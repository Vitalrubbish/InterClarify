# `scripts/remote/setup_env.sh`

项目现名为 ParaThink。优先读取 `PARATHINK_ROOT`、`PARATHINK_ENV_NAME`，兼容 `INTERCLARIFY_ROOT`、`INTERCLARIFY_ENV_NAME`；未指定时新建 `parathink-dev`。创建命令显式传入所选环境名，确保旧环境名覆盖仍然有效。已有环境不随项目更名自动迁移。

## 作用

在登录节点或容器内创建/刷新 `parathink-dev` conda 环境：解释器由 `environment.yml` 固定，第三方包由 `requirements.txt` 固定，pip 默认走清华源。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `INTERCLARIFY_ROOT` | 脚本上两级目录 | 仓库根 |
| `INTERCLARIFY_ENV_NAME` | `parathink-dev` | 环境名 |
| `IC_PIP_INDEX_URL` | 清华 PyPI | pip 源 |
| `IC_RECREATE` | `0` | 置 1 先删除再重建 |
| `IC_INSTALL_DEV` | `0` | 置 1 安装本项目 editable 及 dev 依赖 |
| `IC_CONDA_SH` / `IC_CONDA_BIN` | 用户 miniconda | conda 入口 |

## 流程

1. 可选删除旧环境；
2. `conda env create -f environment.yml`（已存在则跳过）；
3. 解析出环境内 python 绝对路径，打印 pip 版本；
4. `pip install -r requirements.txt`；
5. 可选 `pip install -e .[dev]`。

## 约束

- 集群作业命令中需使用环境内 python 的**绝对路径**，避免误用基础环境解释器；
- **不执行 `pip install --upgrade pip`**：pip 由 `environment.yml` 固定为 24.0，升级会造成实际环境版本漂移；
- 本地环境同样使用 `parathink-dev`，完整版本快照见 `environment.lock.yml`，说明见 [本地环境](../../local_environment.md)。
