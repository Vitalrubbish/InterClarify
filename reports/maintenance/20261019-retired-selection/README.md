# 退役Qwen3-ASR与选型开发实现清理

2026-10-19，用户明确要求删除Qwen3-ASR模型及此前ASR/TTS选型开发实现。已执行并完成删除后检查；本次不改当前推理代码、不训练、不变更实验结论。

## 已删除

- Qwen3-ASR-1.7B专用模型缓存及锁目录：`xtalk-round1/models/cache/models--Qwen--Qwen3-ASR-1.7B`，缓存原占6,475,233,792字节。
- 旧Qwen-ASR源码 `xtalk-round1/qwen-asr`，以及过时远端InterClarify checkout内的Qwen服务、测试、对应说明和pyc。
- 专用conda环境 `miniconda3/envs/xtalk-round1-asr`，删除前保存conda explicit和pip freeze，通过conda卸载后移除该退役prefix的残留文件。当前模型/客户端/训练环境未变动。
- ASR选型 `interclarify-asr-selection/source` 及8份source提交快照、4份重复base64传输包。
- 20261018 TTS选型的source/scripts/configs及source压缩传输包。
- 20261017 TTS screen/analysis/combination/early-fix/latency五个旧开发树内的scripts/tests/configs/docs。其reports和原始运行目录不删，根目录添加RETIRED.md防止继续按旧入口执行。

精确路径和清理前占用见 `cleanup_result.json`、`supplement_result.json`，共47个目录/文件级删除目标。主清单按目标清理前du磁盘块计量约6.25GiB（已扣主恢复归档），不是共享盘配额差值实测；conda硬链接、共享存储和并发写入使其不能等同配额实际减少。补充清理文件量很小，不再估算额外收益。

## 恢复记录与保留项

旧源码压缩成一份约4.03MB的 `retired_selection_sources.tar.gz`，补充远端Qwen服务及传输包恢复记录约99KB，SHA256见结果清单。两份恢复档只保存在远端 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-maintenance-20261019/`，不重复提交源码。Qwen权重不另复制，保留revision/模型文件清单和小型配置元数据，需要时按原来源重新下载。

ASR/TTS原始runs、reports、日志、试听音频，FDB和语料、Kyutai参考二进制、官方DuplexCascade checkpoint/base，当前Nemotron/Kokoro模型和组件环境、独立训练目录均保留。v2–v6的envs实际链接到v1，所以v1/v6保留；Pocket环境虽名为旧候选，仍是现行TTS环境克隆种子，保留不误删。Nemotron多语资产仍被历史复测入口引用，本次只清旧选型实现，没有擅自将其一并退役。X2/MOSS诊断和非本项目环境、共享conda包缓存不动。

## 验证

删除前检查登录节点进程和调度器任务；本次vc list未返回本用户的活动任务行，仅据此和精确引用核对执行清单，不宣称重验了所有跨节点进程。所有受保护路径在删除前后存在；当前NemotronStreamingClient/KokoroSegmented真实导入成功，训练环境python仍在。Qwen模型/专用prefix及清单源码均已不存在，见 `verification_after.json`。没有为验证重新运行GPU实验。

远端操作脚本、恢复档、conda原日志和完整元数据留上述维护目录。本地只回收精确清单、环境包版本、模型来源及校验结果；原始conda日志包含大量终端进度控制符，本地仅保存其摘要和成功结果，来源见log_sources.json。
