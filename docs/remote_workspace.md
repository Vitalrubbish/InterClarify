# 远端工作目录约定

根目录为 `/hpc_stor03/sjtu_home/xuan.zhang/`。远端只保留当前源码、模型、数据、现役 conda 环境与训练入口；实验快照和运行输出使用独立目录，不覆盖既有结果。

| 位置 | 用途 |
| --- | --- |
| `InterClarify` | 当前项目仓库 |
| `xtalk` | X-Talk fork 源码 |
| `DuplexCascade` | 官方 DuplexCascade 参考仓库 |
| `interclarify-p0-models` | 官方基座与 DuplexCascade 权重 |
| `interclarify-asr-selection` | Nemotron 模型、数据与环境种子 |
| `interclarify-tts-selection-20261018` | Kokoro 模型与环境 |
| `interclarify-english-integration-20261018-v6` | ASR/TTS 组件 conda 环境入口 |
| `interclarify-runtime-current` | 当前运行时源码快照入口 |

## 运行约定

- 会话、模型与环境使用 conda；模型和 conda 环境按只读方式复用，不复制权重。
- 每个作业使用独立 `run_id` 与输出目录，保留源码提交、输入摘要、资源上限、退出码和失败日志。
- 维护操作串行执行，优先同文件系统 `rename`，避免复制大模型或音频，也不做无界整盘扫描。
- 删除或迁移前先核对当前作业、磁盘/内存配额和其他项目；原始研究结果不因名称过时直接删除。
- 当前运行快照与稳定入口之间的映射在任务单中登记，作业运行期间不得删除对应源码。
