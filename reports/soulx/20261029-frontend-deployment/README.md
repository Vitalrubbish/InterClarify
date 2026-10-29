# SoulX＋SenseVoice 前端基础部署记录

2026-10-29，贵州 HPC 实际检查完成。复用 TurnControlComparison 的模型、官方源码和 conda，在 `~/parathink-soulx-duplug/` 建立独立入口与软链接，未重新下载或复制权重，未修改共享环境。本次完成资产复用与组件加载验证；Context 接口和完整 Agent 尚未接入。

## 冻结与执行

| 项目 | 实际值 |
| --- | --- |
| ParaThink 入口提交 | `55cc10a`；远端 `source/55cc10a` 为仅含本入口与说明的小型冻结快照 |
| 复用检查源码 | `turncontrol-comparison/source/6de0d70/scripts/remote/check_component.py`；SHA256 见[源码摘要](evidence/source.sha256) |
| 模型与环境 | [部署清单](evidence/deployment.json)；SoulX `61701c4`、SenseVoice `3847d57`、上游 `a0b9063` |
| 实验根与运行 | `~/parathink-soulx-duplug/runs/frontend-smoke-20261029-r1` |
| 调度作业 | `job-179328001617494954185-xuan-zhang`，节点 `d6-hpc-gpu-069` |
| 资源与时限 | 1×RTX 4090、4 CPU、32GiB RAM；组件 400 秒、整体 900 秒，串行执行 |
| 执行时间 | 北京时间约 21:20:19–21:21:55；两个组件分别记录开始时间与真实耗时 |
| 退出 | [退出码](evidence/exit_code.txt)为 0；收尾核对调度列表，本作业已不在活动列表 |

核对当前共享下载 manifest 的 revision、已验证文件清单覆盖与当前文件大小，保存两份 manifest 的摘要；没有重新全量哈希约 8.7GB 的模型文件。两组组件结果保留当次完整包版本，不能用旧环境报告替代本次实际加载。

## 检查结果

| 组件 | 实际行为与结果 | 含加载的耗时 | PyTorch 峰值分配／保留 |
| --- | --- | ---: | ---: |
| SoulX | 权重加载后输入三块 160ms 合成静音，均返回 idle；通过 | 72.10 秒 | 4.64／4.76GiB |
| SenseVoiceSmall | 一秒合成静音及既有英文 dev 音频前八秒；英文返回非空文字，通过 | 19.26 秒 | 0.92／0.99GiB |

上述耗时包含模型加载，不是在线单块耗时或可听延迟；显存数值仅为 PyTorch 分配器统计，不是整个设备或全部进程的显存峰值。收尾 `du -sk` 记录源码快照约 43KiB、单次 run 约 107KiB，权重与环境均为原位置的软链接。

SoulX 加载日志出现官方 `strict=False` 回退；审计确认缺失键为空，仅额外存在 `embed_tokens_func.weight`，且其值与实际输入嵌入完全相同，没有以成功前向掩盖缺失权重。配置见[当次 YAML](evidence/soulx/soulx_config.yaml)，细节见[SoulX 原始结果](evidence/soulx/result.json)及[日志](evidence/soulx.log)。

英文 dev 音频 SHA256 为 `d733a878fbb3393dac0349cfa1293e4fad9a8bd5ec1f58ce6adc019de4b94f32`，实际输入 124800 个 16kHz 采样；此次识别返回关于海外 gap year 课程与升学机会的一段英文。没有参考转写评分，不声明 WER 或准确率。SenseVoice 对合成静音返回 `Yeah.`，已保留在[原始结果](evidence/sensevoice/result.json)及[日志](evidence/sensevoice.log)中；检查只验证调用成功，不把静音识别文字作为真实用户发言，也未据此修改阈值或文本清理。

## 剩余接入

已具备可复用的模型加载基础。下一步是 ParaThink 前端适配：中间转写与修订写入 Shared Context，原生五类状态保留来源、文本版本与观察边界，有效用户打断走直接停止路径。旧项目的 `speak → replies.start` 不能直接搬入本项目。

本次未启动常驻服务，未接入 Layer 0/1/2、TTS 或播放器，未进行原生五状态全面评测、实时回放、完整 benchmark、CoT 注入或训练；不把基础部署通过写成完整研究链路已运行。
