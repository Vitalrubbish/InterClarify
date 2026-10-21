# ASR_R4固定FDB子集回归

2026-10-21。状态：已提交远端调度，回放和评分待完成。用户要求先重跑子集，本次只运行历史固定25例（五类各5例），不运行完整319例、不切换线上候选。

候选`ASR_R4_delayed_punctuation`最终SHA256 `d1f4d05e4ed1b29dbe8550ffaa02be389673975f7929b33ec1420ef2d70c44a1`，训练/重载见[078报告](../../layer1_training/issue078-asr-punctuation-r1/README.md)。原030输入清单SHA256 `d5885326eedab8f450843d3737ce08ccf98ebe6de89d7958b5628a8ba731cc40`，25例70份音频标注，共457.83秒原音频，入场逐文件核验。

运行采用现役X-Talk d6dc3bf、Nemotron EN160/Kokoro af_heart、600ms、TTS首段300ms/后续1200ms、会话KV复用、duplex_greedy_v1和repetition_penalty=1.0。每例独立会话、原始ASR增量，正式output.wav严格等长，5秒尾窗仅作独立诊断。Smooth/Interruption各5例运行官方词级转写及冻结TOR/Latency，GPT相关性仍明确暂缓。

源码`805a12a`已推送，远端独立worktree为训练根目录`source/issue081-805a12a`；只读X-Talk引用065 r4的`source/xtalk`（d6dc3bf干净src）。输出为`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue081-asr-fdb-subset-r1`，提交日志和收据在训练根目录`submit_logs/issue081-asr-fdb-subset-r1.log`及`issue081-asr-fdb-subset-r1-receipt.txt`。

作业`job-179259065594024820461-xuan-zhang`已接收，2×4090/16CPU/64GiB，线程4、worker0、单并发、4小时硬限，20GiB输出/50GiB空闲盘/8GiB单文件。启动前无现役作业，空闲盘约595GiB；所有模型和conda只读复用。先官方对齐预检，后ASR→TTS→模型串行预热，回放完成停服务再评分。

旧T2训练目录不在现役路径，未恢复或重训。接话/打断对照拟从065完整评测中提取同样各5例；不与59/119或160/200的全量聚合直接比较。其他三类历史子集运行配置不同，仅作为带限制的历史观察。本地3项子集边界和6项原评分规则检查、shell语法及Git空白检查通过；真实模型执行和能力结果仍待完成。
