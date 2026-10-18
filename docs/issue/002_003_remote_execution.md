# Issue 002/003 组件接入远端任务单

状态：进行中，自动验收已完成，人工试听未通过，待修复复听。2026-10-18 核对：r4-asr 和 r4-tts 均已远端执行并退出 0；002 已归档，003 的读法试听通过，但分段接续不连续，待 003d 修复及 003c 复听。本任务单包含该未通过条件，暂不归档。仅验证固定 Nemotron/Kokoro 接入，不执行适配训练或 FDB，不把脚本控制轨迹当作真实 LLM 质量验收。

## 已执行与剩余工作

- [x] 独立源码 v6、文件摘要、两个独立 conda 环境及单卡调度作业已留证；实现提交为 InterClarify `d23f80f`、X-Talk `f1531f3`，实际运行源码以快照摘要为准。
- [x] ASR 六场景及尾词交付：作业 `job-179233016243237430568-xuan-zhang`，退出 0，父任务见 [002 归档](archive/002_nemotron_streaming_integration.md)。
- [x] TTS 真实时序脚本文本、取消与原有播放链路自动验收：作业 `job-179233016334530866399-xuan-zhang`，退出 0。
- [ ] [003c 人工试听](003c_audio_listening_review.md)：2026-10-19 用户确认读法正常，但句内分段不连续；待 [003d 修复](003d_segment_continuity.md)及复听通过。

证据见 [r4 接入报告](../../reports/english_integration/20261018-r4/README.md)，原始日志与 WAV 位于远端 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-english-integration-20261018-v6/data/runs/`。以下保留复跑约束，不表示需要重跑已经通过的自动场景。

将当前两仓库源码归档到新的独立 ROOT，生成 `source.sha256`，并保留两仓库提交和工作树实际文件摘要。执行 `ENGLISH_COMPONENT_ROOT=$ROOT bash scripts/remote/setup_english_component_envs.sh`，从已测 conda 种子克隆两个独立环境，保存 conda explicit 与 pip freeze。不得修改历史环境。`run_english_component_job.sh` 显式 BACKEND=asr/tts，每个作业单张 4090、8 CPU、32GB 主存；若模型主存不足，先记录调整理由再提交。每个输出路径必须新建，任务初始上限 30 分钟。通过 vc submit 提交，禁止在登录节点运行真实权重。

ASR 要求首会话、串行会话、长停顿恢复、连续两轮、取消重连、短尾 EOF，保留真实发送计划、迟到、输入摘要、raw/visible 前缀和独立读取。暖机音频为历史 FLEURS dev，只用于预热及接入诊断，不进入训练。TTS 要求短确认、澄清和长文本真实增量，记录分段、首 PCM/首非静音代理、模拟供音断流、取消和新响应代际，保存 WAV。输入文本来源标为固定脚本，不声称真实 LLM 自由生成结果。

有效插话/短附和须另经过原有 RuntimeAdapter→TTSManager→播放事件路径核验；ASR/TTS 接入正确不等于新官方 B0 已接话、整体延迟达标或 FDB 通过。人工听感仍需试听，不能由 PCM 非空判断日期读法和跨段韵律。失败退出码、服务日志、资源采样、依赖、模型摘要和缺测保留原样。全部完成条件满足后将对应父 issue 归档；未满足则保持进行中。
