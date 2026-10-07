# 依赖与模型清单（P0）

对应 [engineering_implementation.md](../../engineering_implementation.md) 第 4.3 节“模型和第三方依赖清单”。版本固定在 [environment.yml](../../environment.yml)（conda 解释器层）与 [requirements.txt](../../requirements.txt)（pip 第三方层）。

## 解释器层（conda）

| 项 | 固定值 | 说明 |
| --- | --- | --- |
| 环境名 | `interclarify-dev` | 本地与集群统一 |
| Python | 3.10 | 与 DuplexCascade 官方一致 |
| pip | 24.0 | |
| conda channel | 清华 conda-forge 镜像 + `nodefaults` | 官方 `conda.anaconda.org` 在集群不可达 |

## 第三方层（pip，节选理由）

| 包 | 版本 | 理由 |
| --- | --- | --- |
| torch | 2.4.1 | 官方要求 `>=2.1`；2.4.1 的 CUDA 12.1 wheel 支持 RTX 4090（sm_89） |
| torchaudio | 2.4.1 | 与 torch 匹配的音频前端 |
| transformers | 4.44.2 | 官方要求 `>=4.40,<5` |
| peft | 0.12.0 | DuplexCascade 用 LoRA |
| accelerate | 0.34.2 | 权重加载/设备放置 |
| huggingface_hub | 0.24.6 | 权重下载（配合 hf-mirror） |
| safetensors | 0.4.3 | `model_state.safetensors` 加载 |
| tokenizers | 0.19.1 | 与 transformers 4.44.2 匹配 |
| numpy | 1.26.4 | 数值基础 |
| scipy | 1.13.1 | 重采样/信号处理 |
| soundfile | 0.12.1 | WAV 读写 |
| librosa | 0.10.2.post1 | 音频特征与重采样 |
| sounddevice | 0.4.6 | 本地设备探测与采集（wheel 自带 PortAudio） |
| websockets | 12.0 | 官方要求 `<14`；ASR/TTS/前端 WS 传输 |
| msgpack | 1.0.8 | 官方 WS 载荷序列化 |
| fastapi / uvicorn / python-multipart | 0.115.0 / 0.30.6 / 0.0.9 | 后续服务壳 |
| requests | 2.32.3 | HTTP 工具 |
| PyYAML | 6.0.2 | 配置加载 |
| pytest | 8.3.2 | 测试 |

## 模型与数据资产（只登记，不入 Git）

| 资产 | 来源 | 固定版本 | 状态 |
| --- | --- | --- | --- |
| DuplexCascade 权重 | `sbintuitions/DuplexCascade` | `31c038ece2f006a28722dd60d1df3868fbb2cc42` | 待 P1 下载，见 [duplexcascade_registry.md](duplexcascade_registry.md) |
| 原版 LLM | `Qwen/Qwen2-7B-Instruct` | 由 `train_cfg.json` 指定 | P1 核对并记录 revision |
| 原版 ASR/TTS | Kyutai `delayed-streams-modeling` | P1 固定 | 语言适配性待验证 |
| Full-Duplex-Bench | GitHub `DanielLin94144/Full-Duplex-Bench` | P1.4 固定 | 本机已有只读副本 |

## 环境复现

```bash
conda env create -f environment.yml
conda run -n interclarify-dev python -m pip install \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
conda run -n interclarify-dev python scripts/check_env.py
```

固定版本的实测结果（版本号、GPU 名称与 `sm_` 算力）记录在 [docs/p0/README.md](README.md) 的验收证据中。
