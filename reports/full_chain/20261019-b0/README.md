# 当前英文完整链路：官方权重B0接话诊断

2026-10-19。结论：**当前Nemotron EN160 → 官方DuplexCascade → Kokoro配置下，历史五例新正文0/5、新语音0/5；需要推进已登记的有限Layer 1适配路线。** 不将这一小样本结果外推为所有语音均不能接话，也不认定句读是唯一原因。

## 实测范围与结果

使用真实ASRManager、600ms产品会话起拍Assembler、RuntimeAdapter及原有TTSManager/协调器/播放管理器，三个真实模型服务均加载并完成readiness。LLM使用完整发布checkpoint、BF16、64-token贪心，Nemotron FP32/160ms，Kokoro为003c已通过的r3实现和af_heart。没有脚本控制token、模拟ASR文本或虚构PCM。

| 历史样本 | micro-turn数 | 控制输出 | 2/5/12秒新正文 | 2/5/12秒新语音 |
| --- | --- | --- | --- | --- |
| candor_turn_taking/1 | 31 | 全部user is talking | 0 | 0 |
| candor_turn_taking/10 | 35 | 全部user is talking | 0 | 0 |
| candor_turn_taking/100 | 36 | 全部user is talking | 0 | 0 |
| candor_turn_taking/101 | 37 | 全部user is talking | 0 | 0 |
| candor_turn_taking/102 | 39 | 全部user is talking | 0 | 0 |

共178拍，原始生成IDs均为 `[151647,151645]`，即 `<|user is talking|><|im_end|>`。每例Nemotron均有可见转写，最大音频投送迟到约2.28ms，协议/组件错误0。观察窗内没有正文，也就未触发回答TTS；这不能被称为完整有声对话通过。Kokoro服务readiness和既有003接入/听感证据不代替本轮缺失的新语音。延迟因全部未回复为null，不报告“平均0秒”。

`per_sample_summary.json`保存最终ASR原文、控制计数和投送迟到；各sample report含全部原始前缀、完整assistant生成IDs、在线事件、输入哈希和供音记录。样本沿用此前已调试五例，不能作为独立训练后测试集，禁止进入训练。

## 时间与产品契约

原音频按80ms/16kHz PCM16实时输入，结束后继续投送12秒记账的静音，维持ASR在线和排出尾词；未发送EOF、ASRFinal或人工让轮状态。标注边界只离线计算2/5/12秒新回复，未交给在线模型。原音频全部保留，诊断尾窗不计官方FDB分数。

采用产品session-start起拍与真实Nemotron raw增量，区别于001的官方Kyutai Word/first-nonempty控制正确性检查。这是产品输入迁移诊断，不推翻001已通过的同输入执行一致性结论，也不通过加句号或改变分拍掩盖失败。

headless播放器按PCM时长确认并准备保存WAV，但本轮无回答音频，未测扬声器或有声停播。没有修改已有TTS首段/后续段策略，不重开组件选型，不增加仲裁器或播放器。

## 运行与决策

远端目录 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-full-chain-b0-20261019/`，作业 `job-179237994657138732632-xuan-zhang`，2×4090、16CPU、64GB主存，LLM独占第一卡，ASR/TTS共用第二卡，三服务并行预热。退出码0只代表诊断完整执行，无接话成功。health、逐文件源码摘要、逐例结果和GPU采样保留，原始日志留远端；JSON仅压缩空白，原件摘要另存。源代码与后续提交分开，run字节不改写。

用户条件“若不能接话则启动训练工作”已满足：启动004的冻结UltraChat来源下载与LFS SHA256核验，以及005的独立conda训练环境准备。正式梯度更新仍需004生成/切分审计、005零更新对齐与训练恢复短跑、007开训前评价规则及样本清单通过；`training_released`仍为false。本轮不声称已经运行训练、不执行完整FDB，不把适配收益提前宣布为通过。
