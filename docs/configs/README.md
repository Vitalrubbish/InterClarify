# 配置模板

统一配置层由 [src/interclarify/config.py](../src/interclarify/config.py) 加载：先读 `base.yaml`，再叠加所选 profile，最后叠加运行时覆盖。三个 profile 覆盖 P0 要求的“本地开发 / 离线回放 / 集群实验”三类环境。

## `base.yaml`

所有 profile 共享的默认值：

- `run`：输出根目录、`run_prefix`、随机种子、标签、会话标识；
- `paths`：仓库根、数据/模型/产物目录（相对仓库根，集群 profile 覆盖为绝对路径）；
- `device`：CPU/GPU 选择与可见卡号；
- `audio`：采样率 24000、单声道、float32、块长 80 ms、设备名、回声消除与冒烟时长；
- `clock`：`real` 或 `virtual`，以及 micro-turn 起点 0.6 s；
- `duplexcascade`：仓库地址与提交、HF 仓库与权重修订、权重文件名与内容 SHA-256（`weight_sha256`）、STT/TTS WebSocket 端点、LLM 端口、`max_new_tokens`、TTS voice 与 STT 预静音默认值；
- `p1_2`：实时双工链路（P1.2）参数——场景定义文件与音频根目录、LLM 服务 `launch|connect`、`reset|reconnect` 场景衔接、播放 sink `auto|virtual|sounddevice`、连接/超时/复位等待等参数，以及 `chunk_event_stride`（`audio_chunk_sent` 事件的降频粒度，避免事件 I/O 污染发送 pacing 测量）；
- `logging`：日志级别与事件文件名。

场景定义 `configs/p1_2_scenarios.json`（入库）声明脚本化用户音频（含合成文本与期望）；其语音音频由 `scripts/prepare_p1_2_scenarios.py` 生成到 `scenario_audio_root`（`*.wav` 不入库）。

## `local.yaml`

本地开发机：`device.backend=cuda`、输入/输出设备为 `default`、`clock.mode=real`。适用对象是带麦克风/扬声器的开发机；集群登录节点没有音频设备，不要使用。

## `replay.yaml`

离线回放：`device.backend=cpu`、无音频设备、`clock.mode=virtual`。用于确定性日志与配置/清单验收，不做模型推理。

## `cluster.yaml`

集群实验：`device.backend=cuda`、`cuda_visible_devices="0"`、无音频设备、`clock.mode=real`；`paths` 覆盖为共享存储绝对路径（`${INTERCLARIFY_ROOT}` 等可覆盖）；`env` 段声明 `HF_ENDPOINT=https://hf-mirror.com`（HF 官方站点在集群不可达）与 `PYTHONNOUSERSITE=True`。

## 版本固定

DuplexCascade 的仓库提交与 HF 权重修订固定记录在 `base.yaml`，并在 [docs/p0/duplexcascade_registry.md](../p0/duplexcascade_registry.md) 说明来源与访问条件；配置摘要（SHA-256）随每次运行写入 `manifest.json`。
