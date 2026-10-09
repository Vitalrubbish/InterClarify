# `configs/xtalk_round1.yaml`

## 整体作用

记录首轮无 System Backchannel 的模型组合、源码来源、conda 环境、端口、分卡与推理参数。它是远端模型准备配置，通过 `scripts/remote/run_xtalk_round1.py` 和服务启动脚本读取，独立于 P0 profile。直接传给 `Xtalk.from_config` 会缺少完整运行时定义，因此只在 ASR 适配完成后转换成全链路配置。

## 字段与边界

- `sources` 固定 X-Talk、Qwen ASR、MOSS 服务封装和 MOSS 模型源码的 Git 提交。
- `models` 记录 ASR、LLM、TTS、codec 与 XTurnix 的 ID；`revision=null` 表示尚未解析，下载工具第一次解析具体 SHA，后续复用锁定文件。
- `environments` 分别指定四个模型服务和准备工具的 conda 环境；不复用 P0 的 torch 2.4.1 环境，不运行会创建 `.venv` 的上游安装脚本。
- `dependency_candidates` 记录固定模型源码要求的 vLLM、Transformers 与 MOSS torch 起始版本；完整依赖以远端验收后的 conda/pip 快照为准。
- `services` 记录已分配 GPU 中的逻辑编号、端口与模型启动参数。`0/1/2/3` 对应申请到的四张 GPU，不代表任意物理卡。
- `asr_streaming` 区分 80 ms 回放步长与内部解码窗口；默认窗口 0.6 秒是待测值。
- `runtime` 声明 ASR 接入待完成；系统附和两项为 `null`。它不包含伪造的可实例化 ASR 类。

模型配置尚未冻结。`models.lock.json` 记录实际模型 SHA 与本地 snapshot 路径；运行报告记录样本校验值、输入参数、首包与修订。环境版本通过远端 `pip freeze` 和 `conda list --explicit` 保存。
