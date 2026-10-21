# Issue 041：整理本地服务器连接说明并忽略提交

状态：完成，已归档。日期：2026-10-20。

按用户要求，将当前机器的服务器连接方式整理为`docs/remote_connection.local.md`，在`.gitignore`加入该精确路径。文档仅本地保存，未加入Git；连接地址、用户名及认证细节不写入本issue。

- [x] 说明Windows/WSL入口、SSH配置来源、交互会话要求及常见连接问题。
- [x] 记录远端只读检查、现役conda与工作区约定，不包含密码、私钥内容或令牌。
- [x] `git check-ignore`命中，Git索引确认未跟踪本地连接文档。

本任务未修改SSH配置、认证文件或远端环境，未提交计算作业。

当前连接文档入口为项目根目录remote_connection.local.md，仍仅本地保存；上述路径是任务完成当时记录，当前操作遵循[远端目录约定](../../remote_workspace.md)。
