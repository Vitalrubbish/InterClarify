# 依赖与底座清单（P0）

版本固定在 [environment.yml](../../environment.yml) 和 [requirements.txt](../../requirements.txt)。当前清单只覆盖仓库现有的通用基础设施；X-Talk 与模型专属 extras 在 P1.0 选型后单独锁定。

## conda 层

| 项 | 固定值 | 说明 |
| --- | --- | --- |
| 环境名 | `interclarify-dev` | 本地与集群统一 |
| Python | 3.10 | X-Talk 固定提交声明 `>=3.10` |
| pip | 24.0 | 避免构建期漂移 |
| channel | 清华 conda-forge 镜像 + `nodefaults` | 适配集群网络 |

## 当前 pip 层

| 类别 | 固定包 | 用途 |
| --- | --- | --- |
| GPU | `torch==2.4.1`、`torchaudio==2.4.1` | CUDA 可见性和通用音频张量 |
| 音频 | numpy、scipy、soundfile、librosa、sounddevice | 冒烟、重采样、WAV 与设备探测 |
| 服务 | websockets、fastapi、uvicorn、aiohttp、requests | 后续 X-Talk 适配所需通用传输 |
| 工程 | PyYAML、pytest | 配置与测试 |

旧路线专属的 transformers、peft、accelerate、safetensors、tokenizers、msgpack 和 Kyutai 依赖已从 P0 固定集移除。若 P1 选择的 X-Talk 组件需要这些包，应按实际 optional extra 和模型版本重新加入并记录理由，不能沿用旧版本假定。

## X-Talk 资产状态

| 资产 | 固定值 | 当前状态 |
| --- | --- | --- |
| 官方仓库 | `https://github.com/xcc-zach/xtalk` | 已登记 |
| 起始提交 | `5f0d9959edf1026588246efbed827b078cbb114c` | 已固定，待导入验证 |
| 集群基础镜像 | `sjtu_yukai-xuanzhang-xtalk:v0.17` | 已存在，待记录 digest 和源码对应关系 |
| ASR/TTS/LLM/turn detector | 未选择 | P1.0 差距审计后固定 |
| FDB | `DanielLin94144/Full-Duplex-Bench` | P1 固定具体提交 |

详细来源和风险见 [xtalk_registry.md](xtalk_registry.md)。
