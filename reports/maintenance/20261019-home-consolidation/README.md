# 远端主目录历史目录归拢

2026-10-19，用户指出主目录仍有大量旧目录。本轮已完成顶层归拢：非隐藏顶层目录由50个减少为26个，24个已结束的InterClarify历史目录移入 `~/interclarify-archive/`，另移入3个传输包并删除空目录 `ic_bctest`。没有在原位置留下同名软链接；未触碰其他项目。

## 当前目录布局

历史对齐、旧英文接入快照v2–v5/v7–v8、001资产/Word对照、B0完整链路、TTS选型及修复r1–r3、retests和p0结果归到 `interclarify-archive/runs/<原目录名>`。先前011维护结果移到 `interclarify-archive/maintenance/retired-selection-20261019/`；三份顶层证据压缩包归到 `interclarify-archive/transfers/`。精确旧/新路径、目录inode及剩余顶层清单见 `result.json`。

顶层目前只剩8个InterClarify现役/依赖目录加归档根：asr-selection（实际模型/数据/环境）、tts-selection-20261018（Kokoro模型及环境种子）、english-integration-v1（实际组件conda）、v6（现行脚本引用入口）、p0-models、kyutai、x2诊断和layer1-training-20261019。名称含selection的两个目录已不保留旧选型开发实现，但仍承载现役资产，不能据名称删除。主仓库、官方参考、FDB/数据源、miniconda和其他项目也保留，因此不把全部主目录压成一个项目目录。

## 执行与验证

所有24个目录都在同一文件系统串行rename，迁移前后inode相同；未复制大目录、模型或音频，未进行大型压缩，未申请集群任务。只维护小型JSON、README和路径记录，不额外创建训练环境或同时遍历整盘统计体积。归拢只减少顶层杂乱，不宣称额外释放了历史数据占用；011的约6.25GiB删除计量保持原结论。

检查当前进程、调度列表和conda环境注册，所有带绝对prefix的现役环境留原位。旧TTS主仓库及3个关联worktree移动后执行git worktree repair，各仓库rev-parse成功；原来有效的软链接迁移后仍有效。现役NemotronStreamingClient/KokoroSegmented导入通过，v6组件prefix和训练python存在；24条旧顶层目录均不存在，新路径和inode核对通过，详见final_verification.json。

原始报告内的旧运行路径、源码摘要和实验字节不修改，以免改写来源。读取历史大日志或恢复旧快照时先查本轮映射，不再按旧主目录绝对路径查找。011源码恢复档现在在上述retired-selection归档目录；012操作记录在 `interclarify-archive/maintenance/home-consolidation-20261019/`。

本轮未重跑模型或宣称训练已启动，不改变任何门禁。原始失败/验收、音频、源码快照仍在归档内；未来新实验应使用独立现役目录，完成后按本布局归档，避免继续向主目录堆放版本。
