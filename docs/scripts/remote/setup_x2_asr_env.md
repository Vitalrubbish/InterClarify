# X2 独立环境准备

`setup_x2_asr_env.sh` 在远端准备 X2Streaming-ASR 的独立推理环境、源码与权重。它与现有 ASR/MOSS 环境完全隔离：官方 requirements 固定 `torch==2.11.0+cu128` 与 `transformers==5.15.1`，与 Qwen3-ASR、MOSS-TTS 的 `torch 2.9.1` / `transformers 5.0.0` 不能共存于同一环境。

## 固定来源

| 项 | 值 |
| --- | --- |
| 源码 | `git@github.com:X-Square-Robot/X2Streaming-ASR.git`，提交 `0aca80597bb1399c0be4002de5bc62c0a779c542` |
| 权重 | `x-square-robot/X2Streaming-ASR-4B-1009`，revision `4c8df16b8d7f8b50c95590c4d7907436ebe4aa08` |
| 默认根目录 | `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2` |
| 默认 conda prefix | `/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/xtalk-x2-asr` |

`INTERCLARIFY_X2_ROOT`、`X2_CONDA_PREFIX`、`X2_CONDA`、`X2_HF_ENDPOINT` 可覆盖默认值。默认走可访问的 HF 镜像 `https://hf-mirror.com`，并关闭 xet 传输（`HF_HUB_DISABLE_XET=1`）。

## 脚本行为

1. **源码**：稀疏检出 `models src demo data_pipeline configs tools`，再切到固定提交。只取推理所需目录，避免拉入训练数据。
2. **环境**：环境不存在时用 `conda create -p <prefix> python=3.12 pip` 新建空的 Python 3.12 基座，而不是克隆共享运行时环境。官方 requirements 会自己拉取匹配的 CUDA wheel，克隆带 torch 的环境只会引入无关包，也更容易因共享环境的版本漂移而不可复现。
3. **依赖**：安装官方 `requirements.txt`，再补 HTTP 服务所需的 `fastapi`、`uvicorn`。安装结果 `pip freeze` 写入 `<root>/requirements.lock.txt`。
4. **权重**：`snapshot_download` 固定 revision 下载到 `<root>/model`，可断点续传（重复运行会复用已有分片）。
5. **校验**：导入 `VoxtralRealtimeForConditionalGeneration`、`torch`、`fastapi`；成功后写 `<root>/ready.txt` 记录源码提交、权重 revision 与环境 prefix。

## 用法

```bash
bash scripts/remote/setup_x2_asr_env.sh
```

只读环境变量即可切换位置；不修改既有 ASR/TTS 环境。依赖下载与权重各约数 GB，首次运行需要较长时间，建议在登录节点用 `nohup` 后台执行并观察日志。

## 与 A4 作业的衔接

节点脚本用 `DUPLEX_ASR_ENV`（conda prefix，不是环境名）以 `conda run -p` 启动 X2 服务，并用 `DUPLEX_X2_SOURCE` / `DUPLEX_X2_MODEL` 指定源码与权重目录；服务启动时校验源码 HEAD 是否等于固定提交。因此 `ready.txt` 的三个路径应原样传入作业环境变量，见 [X2 复测任务单（历史快照）](https://github.com/Vitalrubbish/InterClarify/blob/c614d55/docs/x2streaming_asr_retest.md)。

## 已知边界

- 本环境只在远端服务器创建；本地开发机不需要、也不应升级本仓库的 Python 依赖。
- `pip freeze` 记录的是实际解析结果，官方 requirements 的 pin 是唯一权威版本来源。
- 权重与源码目录位于共享盘，节点作业直接读取；镜像内不需要额外安装。
