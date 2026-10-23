# XTurnix 环境准备

`scripts/remote/setup_xturnix_env.sh` 在远端建立隔离的 XTurnix conda 环境，下载并核对固定 revision 的模型，同时只读复核 Nemotron 资产。脚本不加载 GPU 模型、不回放音频、不覆盖现役 ASR/TTS 环境。

## 模式

| 命令 | 行为 |
| --- | --- |
| `setup_xturnix_env.sh` 或 `prepare` | 克隆测量过的 ASR seed 环境、固定 Transformers、下载模型、校验并写锁 |
| `setup_xturnix_env.sh verify` | 不联网、不改包；按已有锁重新校验环境与模型，写复核记录 |

环境默认位于 `~/interclarify-xturnix-fleurs/envs/xturnix`，从 `~/interclarify-english-integration-20261018-v1/envs/asr` 克隆。克隆使用 conda 的硬链接能力，避免复制大型包；随后在该隔离环境内安装 `transformers==4.57.1`，与模型卡要求的 `>=4.57.1,<6` 和模型自身训练版本一致。

模型默认位于 `~/interclarify-xturnix-fleurs/models/xturnix-pt`，revision 固定为 `d4b0403e5a6744b46fa7602b6d77bbac2768d5b5`。脚本使用 `https://hf-mirror.com`；`model.safetensors` 由 `aria2c` 双连接断点续传，其余文件由 `huggingface_hub` 下载，总并发不超过 2。可用 `HF_ENDPOINT` 覆盖，但不能改变 revision。

## 核心步骤

1. 读取 `configs/xturnix_fleurs_test.json`，要求冻结 revision 与配置一致。
2. 检查工作盘至少 30 GiB 空闲；准备阶段限制 4 CPU、8 GiB RAM。
3. 克隆 seed 环境；已存在时复用，不重新创建。
4. 安装并断言 `transformers==4.57.1`，随后检查 `torch`、`Pipeline` 可导入。
5. 先用 `aria2c` 预下载并续传 `model.safetensors`，再用 `snapshot_download` 补齐小文件；全文件清单必须与上游一致。
6. 大文件比较 LFS SHA256，小文件比较 git blob SHA1；任何缺失、额外文件或摘要不一致立即失败。`.cache`、`__pycache__` 与 `.pyc` 是运行时生成的缓存，不计入冻结清单。
7. 只读复核 Nemotron 的 revision、文件集合和 `model.safetensors` 摘要，不修改其目录；同样忽略运行时字节码缓存。
8. 写入模型锁、pip freeze、conda explicit 清单、模型复核记录和准备报告；配置副本同时保存。

`verify` 模式只执行第 6—8 步的校验部分，用于作业前复核。已有锁与重新计算的文件清单不一致时失败，不会静默重写锁；需要重新冻结时必须显式删除旧锁并由人工确认。

## 环境变量

| 变量 | 默认值 |
| --- | --- |
| `XTURNIX_ROOT` | `~/interclarify-xturnix-fleurs` |
| `XTURNIX_CONDA_BIN` | `~/miniconda3/bin/conda` |
| `XTURNIX_CONDA_SEED` | `~/interclarify-english-integration-20261018-v1/envs/asr` |
| `XTURNIX_ASR_MODEL` | `~/interclarify-asr-selection/models/nemotron_en` |
| `XTURNIX_ASR_LOCK` | `~/interclarify-asr-selection/models.lock.json` |
| `XTURNIX_CONFIG` | 当前源码树中的 `configs/xturnix_fleurs_test.json` |
| `HF_ENDPOINT` | `https://hf-mirror.com` |

## 产物

```text
~/interclarify-xturnix-fleurs/
├── envs/xturnix/                         # 隔离 conda 环境
├── models/xturnix-pt/                    # 固定 revision 权重、tokenizer、turn_pipeline.py
├── models/xturnix-pt.lock.json           # 逐文件 SHA256、字节数、revision
└── environment/
    ├── xturnix_fleurs_test.json          # 配置副本
    ├── xturnix.pip-freeze.txt
    ├── xturnix.conda-explicit.txt
    ├── model_verification.json
    ├── prepare_report.json
    └── verify_report.json
```

报告记录源码提交、配置摘要、空间前后变化、模型与环境 apparent bytes。`apparent bytes` 计入 conda 硬链接的 apparent 大小，不用来宣称实际新增磁盘块；真实新增量以作业前后磁盘差值为准。

## 失败与边界

- 不运行 `conda env remove`，不删除现役环境，不覆盖旧模型目录。
- 下载中断或校验失败时保留失败状态；`aria2c` 的 `.aria2` 控制文件与 hub 的 `.incomplete` 文件允许下一次运行续传，但必须重新校验全部摘要。已有锁与重新计算清单不一致时拒绝静默重写。
- 不在登录节点加载 GPU 模型；真正的预热和推理在调度作业中运行。
- 模型或环境不满足配置时直接非零退出，不把“目录存在”当作已冻结。
