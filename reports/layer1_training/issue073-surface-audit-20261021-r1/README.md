# Issue 073：句读、停顿与ASR表面形式审计

2026-10-21，状态：失败，退出1。用户要求训练文本尽量模仿ASR，重点保留话中句读并适配句末点号缺失。

## 执行身份与范围

源码`d5b57a3ba5615e6858dfa5d4cb872bb8c1b9d914`已推送GitHub，远端使用独立worktree：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/source/issue073-d5b57a3`。不覆盖主仓库或旧数据。

远端运行目录：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue073-surface-audit-20261021-r1`；启动日志在训练根目录`submit_logs/issue073-surface-audit-r1.log`。轻量CPU数据诊断运行于`d6-hpc-debuggpu-001`，非GPU模型或集群性能测试。入口PID 786613，使用现役训练conda，单CPU/线程1、worker0、nice 10、4GiB虚拟地址空间、30分钟、输出2GiB、空闲盘10GiB。启动前`vc list`无作业，空闲盘约591GiB。

输入为040a全部1,000/200/300条对话，manifest SHA256：`86c0faca1e1a12d3c7cf1fa0144e53a6a83166a8454ad48d986b24d40a97761d`；训练索引SHA256：`9032074e05eeb1de7c1c93c396f1e61f0b1e59df67ee21b2c618d167eca9bbfc`。ASR只读历史EN160的200份轨迹（同一100条录音两次运行），不重新加载模型。

本地`ml-hw1` conda和远端训练conda的3项审计边界检查均通过，shell语法与Git空白检查通过。全部数据机器审计已通过，60条卡片已导出；ASR统计遇到一份仅EOF后有文本的轨迹，入口错误要求存在在线文本事件，因`Empty online trace`退出1。失败文件为`shard-0/repeat-0/nemotron_en-160/sample-0065.jsonl`，是有效转写，不应删除或视为模型失败。修复为在线空文本、最终文本正常计入，新增回归后以独立r2重跑；r1不补写成功状态。

## 输入路径核查

当前X-Talk固定`d6dc3bff0a512d13f4352bce6105aec80b7f9960`。Nemotron服务`emit`保留raw/visible及delta原文；`runtime_adapter._append_user`把delta写入用户历史，模型服务`build_prompt_ids`仅处理拍首尾空白，不删除用户句读。`_filter_for_tts`删除点号属于assistant语音路径，不影响ASR用户输入。

现有[ASR报告](../../../docs/asr_selection_report.md)与[表面形式探针](../../asr_text_surface/20261019/README.md)已确认内部句读存在。本轮将重新从原始轨迹区分内部符号、在线末尾和EOF后末尾，并保留缩写/数字中的点号仅作为字符统计的限制；不将内部任意点号一律解释为语义句末。
