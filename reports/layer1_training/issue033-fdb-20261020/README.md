# Issue 033：四配置FDB测试启动

后续结果：100会话已全部完成，作业Completed，总时长55分37秒，轮次及四条件退出0，候选完整推理权重/干净进程生成复现均通过。034诊断确认普遍接话不足，不能以transport PASS称能力通过；详见[诊断与输入ASR核查](../issue034-waiting-asr-20261020/README.md)及四配置能力观察：[B0](b0_capability.md)、[T1](t1_capability.md)、[T2](t2_capability.md)、[T3](t3_capability.md)。官方对齐/评分和人工复核仍pending；下文保留启动时状态。

2026-10-20按用户指令核对首轮训练并启动测试。三训练臂均已完成，详见[完整训练记录](../issue006-round1-20261020/completion.json)：每臂1,214步、2,428序列、1,000条对话，各112个既有LoRA张量更新，冻结参数不变，轮次及各臂退出0；三个最终checkpoint文件内容摘要已再次核验，官方初始完整参数摘要相同。

## 测试作业

作业`job-179248155854367342168-xuan-zhang`，任务`job-179248155854367342168-xuan-zhang-master-0`，已在`d6-hpc-gpu-059`运行。资源2×RTX4090、16CPU、64GiB物理主存，一个并发作业；LLM单卡，Nemotron/Kokoro共享另一张卡。镜像沿用`docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.4`，外层14,400秒，输出上限10GiB、至少15GiB空闲，退出清理服务进程。

- 冻结源码：`fb9e97f`，训练根`source/fb9e97f`独立worktree。
- 训练根：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019`。
- 测试输出：训练根`data/runs/issue033-fdb-r1/`。
- 调度日志：训练根`submit_logs/issue033-fdb-r1.log`。
- 各条件：`B0/`、`T1/`、`T2/`、`T3/`，分别含model.log、model_health.json、client.log、replay及退出码。
- 模型conda：训练根`envs/training`；客户端：`miniconda3/envs/xtalk-round1-client`；ASR/TTS：现役english-integration-v6入口的独立conda。

X-Talk复用008a归档快照419f283；134个src文件逐一核验，与本地当前fork完全一致，不修改远端主xtalk的其他工作。根源码脚本/配置无脏改动，源码已推送GitHub。

## 权重与输入规则

B0保留完整官方权重；T1/T2/T3使用各自首轮最终checkpoint.pt。新候选加载器在同一官方完整模型恢复后，复核固定资产、训练前完整权重身份、完整既有q/v LoRA白名单及shape/dtype，复制后再核对训练最终完整参数摘要。干净服务进程使用训练末尾保存的prompt复现生成IDs，失败就停止该候选启动，不把B0冒充适配权重。每个候选实际验证结论由其model_health.json给出，启动时尚未完成全部候选检查。

030冻结的25个历史input.wav会话、70份原始音频/标注文件摘要均核验通过，暂存路径`inputs/`。固定Nemotron EN160/FP32、Kokoro/af_heart/48kHz PCM16、600ms节拍、BF16/64-token贪心及当前分段参数。四配置顺序为B0→T1→T2→T3，共计划100个独立会话，原生ASR文本不加句读变体、不送未来转写或人工让轮。

复用既有A4音频与播放取消驱动。本轮原音频后连续发送5秒记账静音帮助流式ASR排出尾词，报告标记diagnostic_tail_audio；官方WAV始终截断/补齐至原始输入长度，尾窗另存diagnostics，不把窗外回复计入官方窗口。此行为是公开的诊断输入策略，不冒称尾窗属于FDB原始音频。

## 启动证据

[启动快照](startup_snapshot.json)采集于北京时间15:38:56：作业Running，ASR和TTS预热成功，B0完整官方模型已就绪且健康条件明确为B0。25会话清单、70原始文件和134个X-Talk源文件校验通过。

以下远端测试全部通过、无跳过：

- [候选白名单及清单边界4项](startup/test_layer1_candidate.py.txt)。
- [公共加载/真实CPU张量7项](startup/test_layer1_loading.py.txt)。
- [模型HTTP与token契约6项](startup/test_duplex_model_service.py.txt)。
- [A4驱动/取消/诊断尾窗18项](startup/test_duplex_a4_replay.py.txt)。

快照时B0已有4份真实Candor pause样本结果（1/10/100/101），未记录传输、协议或组件错误，均为静默输出。暂停样本静默不能直接当漏答或语义通过；其semantic_status保持PENDING_OFFICIAL_SCORING。其他样本及候选按作业顺序继续执行，不能把启动快照当全轮完成。

## 仍待完成

全部候选干净进程复现、四配置100会话推理、原始输出回收及四份能力报告尚未完成；官方FDB对齐/评分和内容人工检查尚未执行，均保留pending。当前35项测试证明边界和驱动执行契约，不证明接话、等待或有效插话能力。

006仍需候选干净进程恢复复现和移交完成，007负责汇总能力报告，008继续测试及后续评分。历史小子集是回归能力描述，不是完整FDB或独立未见验收。本地原有AGENTS.md修改及两份规范删除保持原状。
