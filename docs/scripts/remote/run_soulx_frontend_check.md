# SoulX 前端远端加载检查入口

对应 `scripts/remote/run_soulx_frontend_check.sh`。脚本只负责复用已验证组件检查，模型资产、版本和范围见[部署说明](../../dev/SoulX-Duplug/deployment.md)，没有业务类。

入口使用 `SOULX_ROOT` 指定独立结果根，`SOULX_ASSET_ROOT` 指定 TurnControlComparison 资产根，`SOULX_CHECK_SOURCE` 指定冻结组件检查源码，`SOULX_RUN_ID` 指定唯一运行名。默认读取已核查路径，验证 conda 标识和加载器 SHA256 后，串行运行 `soulx`、`sensevoice` 两个组件，保留每步日志与原始 JSON。

主要步骤包括：单作业文件锁、拒绝覆盖旧目录、检查 30GiB 空闲盘、关闭下载与用户包注入、隔离缓存、保存源码和环境来源、执行带时限的 GPU 检查、保存真实退出码。内嵌 Python 只读取 manifest，核对两组冻结 revision、验证清单覆盖和当前文件大小并保存清单摘要，不导入模型，也不重复全量哈希大型权重。已有检查入口审计 SoulX 权重缺项与嵌入别名，显存分配比例为 0.83；不由 shell 在登录节点加载模型。

通过 `vc` 提交 1 GPU、4 CPU、32GiB 作业，整个脚本外加 900 秒时限；每组件内加 400 秒时限。可在已分配 GPU 的作业内运行：

```bash
SOULX_RUN_ID=frontend-smoke-20261029-r1 timeout -k 20s 900s \
  bash scripts/remote/run_soulx_frontend_check.sh
```

`runs/<run_id>/` 保存 `deployment.json`、`source.sha256`、`soulx.log`、`sensevoice.log`、两个组件的 `result.json`、`exit_code.txt`，以及加载器建立的配置和离线软链接视图。两个组件成功只说明可加载和运行局部前向，不表示五状态全部验证、中间文字已发布、满足实时性或整个语音 Agent 已部署。
