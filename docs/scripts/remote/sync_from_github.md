# `sync_from_github.sh`

## 文件作用

`scripts/remote/sync_from_github.sh` 是服务器端的代码同步入口。服务器从 GitHub `main` 分支更新 InterClarify 工作树，避免依赖开发机到集群的直接 SSH 或文件复制。脚本只更新干净工作树；发现服务器 checkout 有未提交改动时立即失败。

## 核心步骤

1. 目标目录不存在时，用 HTTPS GitHub 地址克隆 `main`；
2. 目标目录已存在时，检查工作树、校正 `origin` 地址、获取远端分支并执行 `git pull --ff-only`；
3. 输出最终提交号和工作树状态，供后续任务单记录。

## 环境变量

- `INTERCLARIFY_ROOT`：服务器 checkout 路径，默认 `/hpc_stor03/sjtu_home/xuan.zhang/InterClarify`；
- `INTERCLARIFY_GIT_URL`：GitHub 地址，默认 `https://github.com/Vitalrubbish/InterClarify.git`；
- `INTERCLARIFY_GIT_REF`：分支，默认 `main`。

脚本不包含 GitHub 凭据。若仓库访问需要认证，应使用服务器已有的 Git credential helper 或集群密钥配置；不要把 token 写入命令行、脚本或证据文件。
