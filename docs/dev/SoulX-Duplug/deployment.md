# 远端前端部署与资产复用

更新：2026-11-05。当前前端为 SoulX-Duplug 原生控制＋独立 X2Streaming-ASR。本文只记录只读复用的模型、conda 与源码资产，具体实验结论以对应报告为准。

## 1. 共用资产

远端共用资产根为 `/hpc_stor03/sjtu_home/xuan.zhang/turncontrol-comparison/`，ParaThink 只读复用，不复制或修改。

| 资产 | 相对路径与版本 |
| --- | --- |
| SoulX conda | `envs/soulx`，Python 3.11；torch/torchaudio 2.6.0+cu126、Transformers 4.52.1、FunASR 1.2.6 |
| SoulX 权重 | `models/soulx-duplug`，revision `61701c4ab8193cc1ee2220d3848872ac6c720142` |
| SenseVoiceSmall | `models/sensevoice-small`，revision `3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`，英文 `language=en` |
| X2Streaming-ASR | `models/x2streaming-asr`，revision `4c8df16` |
| X2 官方源码 | `upstream/frozen-20261028/x2streaming-asr`，提交 `0aca80597bb1399c0be4002de5bc62c0a779c542` |
| 官方 SoulX 源码 | 本地子模块 [third_party/soulx-duplug](../../third_party/soulx-duplug.md)，提交 `a0b9063843df69619b087b95b74597b2176910b8` |

模型与源码摘要冻结在 `configs/native_soulx.json` 与 `configs/x2_streaming_probe.json`，执行前核验，不运行时升级或重新筛选 ASR。

## 2. 独立根目录

ParaThink 使用独立根目录 `~/parathink-soulx-duplug/`，源码、提交日志和结果单独存放；模型与 conda 通过软链接只读复用，不重新下载或复制约 8.7GB 的模型文件。运行结果写入 `runs/<run_id>/`，不写共享资产。

## 3. 执行入口

| 入口 | 用途 |
| --- | --- |
| [run_native_frontend_probe.sh](../../scripts/remote/run_native_frontend_probe.md) | 通用前端预热、回放与单卡诊断 |
| [run_x2_streaming_probe.sh](../../scripts/remote/run_x2_streaming_probe.md) | X2 单路离线实时探针 |
| [native_frontend_probe.py](../../scripts/remote/native_frontend_probe.md) | 双路调度、联合提交和资源记账 |
| [run_fdb30_half_duplex.sh](../../scripts/remote/run_fdb30_half_duplex.md) | 当前完整半双工评测，资源见对应说明 |

预热音频由 `SOULX_WARMUP_AUDIO` 指定为本地 7.8 秒英文语音，不绑定特定数据集路径。远端作业使用 1×RTX 4090、4 CPU、32GiB RAM、单并发；显存停止线 22GiB，PCM 总量 4MiB，输出 128MiB，单作业 1800 秒。资源触限保留失败，不自动扩容、重试或减速送音。

## 4. 边界

- 复用官方模型加载、原生推理与 X2 因果解码；动作消费与发布屏障按当前前端合同执行。
- 五类用户状态写入 SharedContext，由下游在当前 turn 读取有效 `user_complete`；有效用户打断单独停止输出。
- 普通 LLM／TTS 与播放实录已用于[独立半双工评测](fdb30_half_duplex.md)；前端探针通过不等于 X-Talk 常驻集成、Layer 1 训练或 CoT 注入已完成。
