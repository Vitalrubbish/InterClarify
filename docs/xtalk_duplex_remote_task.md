# 阶段 A 官方权重远端验证任务

## 源码与资产

实现位于本地 X-Talk dev 工作树，远端只运行独立同步副本。每个文件的 SHA256 写入 source_manifest.json，作业执行前校验；记录父提交 9c131ed，未提交补丁通过内容摘要识别。服务器已有官方模型和 Qwen2 基础模型，使用镜像中客户端 conda 与共享 interclarify-dev 模型 conda；测试不启动训练。

官方 checkpoint：/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28。
基础模型：同级 Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a。
远端 tokenizer 已核实：no voice=151646、talking=151647、finish=151648、thinking=151649、interruption=151650、backchannel=151651、im_end=151645。

## 顺序与判据

1. 当前本地源码完成协议、窗口、播放链路和 HTTP 契约测试。
2. 同步源码至独立 xtalk-duplex-dev/<摘要> 目录，校验 manifest。
3. pdgpu-4090 申请 2 GPU、8 CPU、64G（队列每 GPU 最多 32G；模型只使用逻辑 GPU 0），执行 run_xtalk_duplex_node_job.sh。
4. 检查严格 checkpoint 装载、token IDs、健康检查和模型 micro-turn 原始输出；至少一段回答、无协议错误，输出回收本地。
5. 此任务只验证真实 LLM 与运行时连接，后续 A4 补充真实 ASR/MOSS 音频、长会话、延迟与 FDB。不能将模拟 PCM 记录作为音频质量结论。


## 当前记录

本地验证：X-Talk 137 项（134 PASS、3 skipped），InterClarify 24/24；A2/A3 行为门禁 15/15。首个同步包 ca969f62c2e4 校验清单为 3fc882a68624147c49800aec4f099724865d397f2d0553e68abfbb2f95194355；补丁更新包 558aa89e52a4 清单为 36a5645f544fc175dc1ba688bbce5fe2b0e202b36ae9df6bacb0cf226fa21a68。它们都是本地源码快照，工作树后续更新需另生成摘要。

首轮作业 job-179179437499733903832-xuan-zhang 已提交至 pdgpu-4090，节点 d6-hpc-gpu-052，2 GPU/8 CPU/64Gi；容器启动后 160 份文件 SHA256 校验通过，模型 conda 依赖符合记录；模型加载因旧 fast tokenizer 无法读取发布 tokenizer.json 失败，该作业已关闭。实际权重尚未进入 GPU。

最新源码快照 930c7ac12ceb 已同步，清单 SHA256 为 9b601d6732a6495965f58a1700a0a412968aab1cbfa14f09835a8a05043867fa；它包含即时打断和动作前 response ID 观测补丁。最终模型复测应以此快照或后续更新为准。

远端显式 slow tokenizer 验证：Qwen2Tokenizer、词表 151652、finish talking=[151648]，ChatML sample=[151644,872,198,9707,151645,198]。修复后的本地快照 3441d5591407 待复测，使用同一发布 vocab/merges/added_tokens。

修复包清单 SHA256 为 f8f5c7ea6f3bac369afaac35bac96607914cd99b245a353253913b38ef80f646。源码清单与回收日志保存在被 Git 忽略的 data/runs 下，任务文档只登记摘要和结论。

复测作业 job-179179536527075399718-xuan-zhang 已提交至 pdgpu-4090，运行修复快照 3441d5591407。正式远端通过须以该作业的 health/report 为证据。

第二轮 3441d5591407 已通过 tokenizer 和基础模型加载，严格权重校验发现发布 q/v 基础层键与当前 PEFT base_layer 层级差异；实现显式键迁移并保持严格装载，未使用随机缺失层继续服务。

第三轮快照 17fd22d55cc7 已同步，source_manifest.json SHA256=4d366590420f41b3c2cd236aef023ab04fb5def89ed38c4b6bcd82d7c0be2fbe，作业 job-179179566806951798391-xuan-zhang，复测显式 q/v 基础权重键迁移与严格 state dict 装载。


## 最新通过结果

第三轮 job-179179566806951798391-xuan-zhang 使用本地源码快照 17fd22d55cc7，源文件校验 160/160，通过官方权重严格加载。health 显示 Qwen2Tokenizer、BF16、context_length=32768，全部 special token ID 与发布一致。运行时 report status=PASS、outputs=12、errors=0，出现正常回答文本。

本轮使用真实官方 LLM、脚本 ASR 前缀、原生 TTS/coordinator/playback 和模拟 PCM。不能替代真实音频或 FDB；A4 剩余项目见改造计划。原始 health、报告与 JSONL 回收到 data/runs/duplex-17fd22d55cc7/，运行来源路径应位于该快照 xtalk/src。

回收报告核验：作业 Completed，运行路径为独立快照 xtalk/src/xtalk；report.source_sha256 与当前本地 xtalk/src/xtalk 的 Python 源码逐文件摘要一致。真实回答为 The capital of France is Paris.，原生播放结算的 heard 文本一致；状态序列含 user is talking、user finish talking 和 user is thinking。此单例没有覆盖真实模型的用户附和或打断质量，仍需 A4 场景验证。

X-Talk 最新提交 `2f8a43343dd83153298c416d270a8843b023abc0` 包含 user backchannel 同一 micro-turn 续写；2026-10-13 的第二轮官方对齐把打断改为"播报窗口内 reset 未播音频 + 继续解码到 `<|im_end|>`"，assistant 历史改存 token id。当前本地 X-Talk 142 项（139 PASS、3 skipped），A1 定向 35/35，A2/A3 行为 34/34；InterClarify 根仓库 40 项。17fd22d55cc7 是此前已通过的官方模型 smoke 快照，不能代表当前提交的真实 ASR/MOSS/FDB 已复测。A4 新的远端入口和判据见 [xtalk_a4_remote_acceptance.md](xtalk_a4_remote_acceptance.md)。

## A4 入口

最新工作树需要重新生成 `source_manifest.json` 后再同步到服务器。提交和节点入口为：

```bash
conda run -n paratalker-dev python scripts/remote/create_duplex_source_manifest.py
export INTERCLARIFY_DUPLEX_ROOT=/shared/xtalk-duplex-a4/current
bash scripts/remote/submit_xtalk_duplex_a4_job.sh
```

入口默认申请 3 GPU，执行 A1–A3 回归、官方权重 smoke、真实 WAV 回放、interruption/long-session 场景和可选 FDB 对齐/评分。缺少 FDB 数据或固定评分环境时记录 `BLOCKED`；模型没有输出指定语义 token 时记录 `INCONCLUSIVE`。这些状态不会覆盖第三轮历史 smoke 结论。
