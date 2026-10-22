# cleanup_remote_assets.sh

## 作用

在远端登录节点盘点或删除 InterClarify 旧路线资产。默认 `--dry-run`，只打印目标与大小；`--execute` 需要同时设置 `CLEANUP_CONFIRM=YES`。

## 输入

| 参数/变量 | 默认 | 说明 |
| --- | --- | --- |
| `--dry-run` | 默认 | 列出目标、`du -sh` 大小和 conda 环境，不删除 |
| `--execute` | 关闭 | 执行删除；必须同时设置 `CLEANUP_CONFIRM=YES` |
| `CONDA_BIN` | `~/miniconda3/bin/conda` | conda 入口 |

## 安全边界

- 所有目标必须位于当前 `$HOME` 下；拒绝 `/`、home 本身和保留前缀。
- 保留当前权重、现役 ASR/TTS 环境、运行时快照、FDB r4、benchmark、`full-duplex-bench` 与 `interclarify-dev`。
- 串行执行，不并发；不跟随符号链接；conda 环境用 `conda env remove` 删除，同时处理 `.conda/envs` 下的旧环境。
- 执行前后记录 `df -h`，日志写入 `~/cleanup_remote_assets.<mode>.log`。
- 不处理 `STS`、`Paratalker`、`ParaTalker`、`sidecar` 等其他项目。

## 使用

```bash
bash scripts/remote/cleanup_remote_assets.sh --dry-run
CLEANUP_CONFIRM=YES bash scripts/remote/cleanup_remote_assets.sh --execute
```

本脚本不建立新的模型能力结论；清理通过只表示目标路径已删除且保留项仍存在。
