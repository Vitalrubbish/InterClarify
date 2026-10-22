# Issue 089：清理远端服务器旧路线资产

状态：完成，2026-10-22。dry-run 与执行均完成；磁盘由约 430G used / 595G avail 降至 129G used / 896G avail，释放约 301G。保留项已核验存在，组件与评分环境可导入。

## 范围

远端根目录为 `/hpc_stor03/sjtu_home/xuan.zhang`。当前无活动作业（`vc list` 为空），磁盘约 430G used / 595G avail。清理目标是旧 Layer 1 训练、旧 ASR/TTS/X2/Kyutai 栈、旧运行结果、下载缓存和旧 conda 环境；不触碰其他项目（`STS`、`Paratalker`、`ParaTalker`、`sidecar` 等）。

## 保留项

| 路径 | 用途 |
| --- | --- |
| `interclarify-p0-models/modelscope` | Qwen2-7B 与 DuplexCascade 权重 |
| `interclarify-asr-selection/models` | Nemotron 与 alignment |
| `interclarify-tts-selection-20261018/models` | Kokoro 模型 |
| `interclarify-english-integration-20261018-v1/envs` | 现役 ASR/TTS conda；v6 软链到此 |
| `interclarify-english-integration-20261018-v6` | 现行组件入口 |
| `interclarify-runtime-20261021-adopted` | 当前运行时快照 |
| `InterClarify/benchmark/fdb_v1_0` | FDB 评测数据 |
| `Full-Duplex-Bench`、`DuplexCascade` | 官方仓库 |
| `interclarify-fdb-two-axes-20261021-r4` | FDB 最终结果 |
| `miniconda3/envs/full-duplex-bench` | FDB 评分环境 |
| `miniconda3/envs/interclarify-dev` | 远端通用/模型服务环境 |
| `xtalk` 源码与 `frontend` | 远端 X-Talk 仓库；只清其模型、缓存、日志和 node_modules |

## 删除组

| 组 | 路径 | 约计 |
| --- | --- | ---: |
| xtalk 模型库 | `xtalk/models` | 175G |
| xtalk 缓存/日志 | `xtalk/.hf_cache`、`.modelscope_cache`、`logs`、`index-tts-vllm`、`arXiv-2512.18706v1` | 4.9G |
| 旧训练根 | `interclarify-layer1-training-20261019` | 16G |
| 旧选型环境 | `interclarify-asr-selection/envs`、`interclarify-tts-selection-20261018/envs` | 15.4G |
| 旧选型数据 | `interclarify-asr-selection/{dataset,runs,reports,logs}`、`interclarify-tts-selection-20261018/{runs,export_*,logs}` | 约 424M |
| Kyutai | `interclarify-kyutai`、`interclarify-p0-models/kyutai` | 16.7G |
| X2 | `interclarify-x2` | 8.3G |
| round1 | `xtalk-round1` | 9.6G |
| 归档 | `interclarify-archive` | 506M |
| 旧 FDB 运行 | `interclarify-fdb-two-axes-r1/r2/r3` | 1.1G |
| 旧延迟/生成诊断 | `interclarify-latency-r1/r2`、`kv-diagnosis-r1/r2`、`generation-policy-r1` | 503M |
| 旧运行证据 | `InterClarify/data/runs` | 1.1G |
| 临时文件 | `ic_p0_tmp`、`logs`、`fdb_env_build.*`、`*.pipfreeze.*`、`inventory_*` | < 10M |
| 旧 conda 环境 | `moss-debug`、`xtalk-round1-client`、`xtalk-round1-moss`、`xtalk-round1-tools`、`xtalk-round1-turnsense`、`xtalk-round1-vllm`、`xtalk-x2-asr` | 约 18G |
| 下载缓存 | `~/.cache/{pip,huggingface,modelscope,puccinialin,vllm,flashinfer,torch,numba,matplotlib,xtalk}`、`miniconda3/pkgs` | 约 19G |

不删除 `paratalker-dev` 与 `sidecar`，它们属于其他项目；`interclarify-dev` 保留为远端固定环境。

## 执行方式

脚本：`scripts/remote/cleanup_remote_assets.sh`。

```bash
# 只列目标与大小
sh scripts/remote/cleanup_remote_assets.sh --dry-run

# 确认后执行
CLEANUP_CONFIRM=YES sh scripts/remote/cleanup_remote_assets.sh --execute
```

脚本检查：

- 默认 dry-run；`--execute` 必须同时设置 `CLEANUP_CONFIRM=YES`。
- 每个删除目标必须位于当前 home 下，拒绝 `/`、home 本身、保留路径和未知路径。
- 串行执行，不并发；记录 `df -h` 前后、每项路径、执行时间与退出码。
- conda 环境通过 `conda env remove` 删除，不直接 `rm -rf`；最后执行 `conda clean -a -y`。
- 不跟随符号链接；`interclarify-runtime-current` 只删除链接本身（若纳入），不删除目标。

## 执行结果

dry-run 与执行日志位于远端：

- `~/cleanup_remote_assets.dry-run.log`
- `~/cleanup_remote_assets.execute.log`
- `~/cleanup_second.log`（`.conda/envs` 下的 `verify312`、`xtalk` 与 `.conda/pkgs`）

执行后固定环境：

| 用途 | 环境 |
| --- | --- |
| 通用/模型服务 | `~/miniconda3/envs/interclarify-dev`（torch 2.4.1+cu121，transformers 4.46.3，peft 0.13.2） |
| FDB 官方评分 | `~/miniconda3/envs/full-duplex-bench`（torch 2.6.0+cu126） |
| ASR 组件 | `~/interclarify-english-integration-20261018-v1/envs/asr`（torch 2.11.0+cu128，transformers 5.15.1） |
| TTS 组件 | `~/interclarify-english-integration-20261018-v1/envs/tts`（torch 2.11.0+cu128） |

保留的 `paratalker-dev`、`sidecar` 属于其他项目；`STS`、`Paratalker`、`ParaTalker` 等未触碰。`vc list` 为空，未启动新作业。

## 验收

- [x] dry-run 输出目标清单与大小，人工确认无保留项。
- [x] 执行后 `df -h` 显示释放空间；脚本退出码 0。
- [x] `interclarify-p0-models/modelscope`、`interclarify-asr-selection/models`、`interclarify-tts-selection-20261018/models`、`v1/envs`、`v6`、`runtime` 快照、FDB r4、`benchmark` 仍存在。
- [x] `full-duplex-bench` 与 `interclarify-dev` 可启动；组件 ASR/TTS env 的 `conda-meta/history` 存在。
- [x] 不把 dry-run 或执行通过写成模型能力验收。
