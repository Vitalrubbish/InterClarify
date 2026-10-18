# `scripts/remote/setup_fdb_scoring_env.sh`

## 功能与边界

把 FDB v1.0 对齐与评分所需的环境（默认 conda 环境 `full-duplex-bench`）固定到**可与集群驱动共存的组合**：CUDA 12.x 版 torch 与 NeMo 2.x。

不锁版本时会出现三个必然失败：

- 普通安装解析到的 torch 是 `+cu130` 构建，需要 CUDA 13；本机与集群 4090 节点的驱动均为 570.x（仅到 CUDA 12.8），CUDA 初始化直接报 `NVIDIA driver on your system is too old`；
- `nemo_toolkit 3.0.0` 把 `ASRModel` 变成抽象类（`setup_training_data` / `setup_validation_data` 成为 abstractmethod），官方 `get_transcript/asr.py` 的 `ASRModel.from_pretrained("<parakeet 归档>")` 会抛 `Can't instantiate abstract class ASRModel`。FDB 官方代码按 NeMo 2.x 编写；
- `cuda-python` 的 bindings 只声明宽松版本区间（NeMo 2.6.2 里是裸 `cuda-bindings`），NeMo 降级或升级都不会把它调整到合适版本。NeMo 2.6 的 TDT 解码默认走"conditional node CUDA 图"（`CudaGraphsMode.FULL_GRAPH`），那条路需要 CUDA 13 bindings + 驱动 ≥580：CUDA 12 bindings 返回的元组长度与 NeMo 的解包不符（`expected 6, got 5`），CUDA 13 bindings 则在驱动 570 上做图捕获时 `cudaErrorInsufficientDriver`。官方 `get_transcript/asr.py` 没有开关可绕开，所以脚本**卸载 `cuda-bindings`**，让 NeMo 走它自己 try/except 保护的分支：`CudaGraphsMode.NO_WHILE_LOOPS`（纯 torch 图 + Python while，数值等价，只是慢）。
- 同一个 `asr` extra 还带进 `numba-cuda`，它在缺 `cuda-bindings` 时会拒绝导入（NeMo 的 ASR 导入链会触发）。脚本按其官方提示设置环境变量 `NUMBA_CUDA_USE_NVIDIA_BINDING=0`，让 numba 改用直接调用 libcuda 的 ctypes bindings；该变量用 `conda env config vars` 持久化到环境里，所有 `conda run -n <env>` 都会继承。

脚本不下载模型权重、不跑推理；权重由 `get_transcript/asr.py` 首次运行时从 Hugging Face 取（本机已有 `nvidia/parakeet-tdt-0.6b-v2` 缓存）。

## 已知缺口：环境尚未完全自足（2026-10-15）

当前 `full-duplex-bench` 的 `site-packages` 里只有 NeMo、torch、openai、numba 等，`numpy`、`scipy`、`soundfile`、`tqdm`、`typing_extensions` 并不在其中——它们由共享 user site（`~/.local/lib/python3.11/site-packages`）提供。原因是上次安装时 user site 处于启用状态，pip 认为这些依赖"已满足"而跳过写进环境。

后果：节点作业/容器导出 `PYTHONNOUSERSITE=True`，user site 被隐藏，官方 `asr.py` 因缺 `soundfile`、官方 `evaluate.py` 因缺 `typing_extensions`（经 `openai` 间接导入）直接失败。评分入口因此必须保持 user site 启用（`unset PYTHONNOUSERSITE`），见 [run_fdb_llm_judge.py](run_fdb_llm_judge.md)。

彻底修法是重装环境时在脚本开头 `export PYTHONNOUSERSITE=1` 再装依赖，使这些包落入环境自身；本轮未重装以免扰动已验证的 NeMo/torch 组合，记为后续清理项。

## 关键步骤

1. 落 `pip freeze` 快照到 `FDB_PIPFREEZE_SNAPSHOT`（默认 `/hpc_stor03/sjtu_home/xuan.zhang/<env>.pipfreeze.<UTC 日期>.txt`），保留回滚依据。
2. 从 PyTorch 官方索引装 torch/torchaudio（默认 `https://download.pytorch.org/whl/cu126`，版本 `2.6.0`）。
3. 从 PyPI 镜像（默认清华源）装 `nemo_toolkit[asr]`（默认 `2.6.2`）。
4. 卸载 `cuda-bindings`，使 NeMo 走 `NO_WHILE_LOOPS` 回退而非 conditional-node CUDA 图；并把 `NUMBA_CUDA_USE_NVIDIA_BINDING=0` 写入环境配置，供 `numba-cuda` 在无 bindings 时使用 ctypes。
5. 自检：打印 torch 版本、CUDA 可用性、NeMo 版本、`ASRModel.__abstractmethods__`、numba.cuda 与 cuda-python 是否可导入，并实跑一次 CUDA graph capture。

关于第 5 步的 `__abstractmethods__`：NeMo 2.x 的 `ASRModel` 仍是抽象类（`setup_training_data` / `setup_validation_data`），但 `from_pretrained` 由归档配置里的 `_target_` 派发到具体类（实测得到 `EncDecRNNTBPEModel`），所以该字段非空并不代表官方脚本不可用；真正的判据是 graph capture 与一次对齐能跑通。

## 用法

```bash
bash scripts/remote/setup_fdb_scoring_env.sh
```

可覆盖的环境变量：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `FDB_ENV_NAME` | `full-duplex-bench` | conda 环境名 |
| `CONDA_SH` | `/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/etc/profile.d/conda.sh` | conda 初始化脚本 |
| `FDB_TORCH_INDEX` | `https://download.pytorch.org/whl/cu126` | torch 轮子索引 |
| `FDB_TORCH_VERSION` | `2.6.0` | torch/torchaudio 版本 |
| `FDB_NEMO_VERSION` | `2.6.2` | NeMo 2.x 版本 |
| `FDB_PYPI_MIRROR` | `https://pypi.tuna.tsinghua.edu.cn/simple` | NeMo 依赖来源 |
| `FDB_PIPFREEZE_SNAPSHOT` | `/hpc_stor03/sjtu_home/xuan.zhang/<env>.pipfreeze.<日期>.txt` | 变更前快照路径 |

## 与其它脚本的关系

环境修好后，用 [run_fdb_llm_judge.py](run_fdb_llm_judge.md) 跑官方对齐与 judge；节点作业 [run_xtalk_duplex_a4_node_job.sh](run_xtalk_duplex_a4_node_job.md) 的 `DUPLEX_A4_FDB_SCORING=1` 分支复用同一套官方命令，二者的判据一致。
