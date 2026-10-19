# 实际删除退役候选与旧编译缓存

2026-10-19，承接用户“有些可以直接释放”的要求。本轮是直接删除，不是移动归档；原始ASR/TTS结果、日志、音频和现役环境保留。

| 已删除类型 | 数量 | 删除前目标磁盘块占用 |
| --- | --- | --- |
| 已结束TTS实验的Inductor/Triton编译缓存 | 14个目录 | 0.83GiB |
| Nemotron多语、旧Python Kyutai和Pocket候选模型 | 3组 | 4.79GiB |
| Nemotron多语与旧Python Kyutai专用conda环境 | 2套 | 14.96GiB |
| 合计 | 19个目标 | 20.58GiB |

精确路径和逐项字节见result.json，合计22,095,687,168字节。本值来自每个目标删除前串行du磁盘块计量，不冒充共享存储配额差值或精确物理回收量：conda硬链接和存储共享会影响实际配额收益。收益与011的Qwen3-ASR删除分开，012目录rename不计入。

## 核验与删除边界

现行代码/配置和任务没有上述候选实时模型及prefix引用；历史复测只读已保存轨迹，权重可按来源重新下载。旧Python Kyutai与Rust参考权重大小不同，本轮按退役资产删除，不伪称字节相同去重。保留模型配置、来源/完整文件SHA256和环境conda/pip清单；只保存小型元数据，不复制大权重、不重打包编译缓存。原始实验WAV、日志、JSON和源音频不删。

删除范围仅为冻结清单，已核对登录节点进程和调度器本用户任务；没有新增CPU/GPU集群作业。实际操作串行，模型哈希读取块1MiB，未进行全盘并发扫描。环境通过conda卸载，再清理该已导出退役prefix的pip残留；首次conda env remove不接受--offline参数，失败记录保留，改用CONDA_OFFLINE=true后两套环境成功卸载。没有清空共享conda包缓存。

保留且删除后检查存在：Nemotron EN模型/种子，Kokoro模型及当前组件环境，Pocket环境种子（当前克隆入口仍依赖它，不是Pocket权重），Rust Kyutai STT参考二进制/权重/其Python运行依赖，官方checkpoint/base、当前客户端及独立训练环境。当前NemotronStreamingClient/KokoroSegmented导入通过，原始ASR/TTS运行目录仍在，19个退役目标均不存在。详见verification_after.json。

## 来源与后续

完整操作原件、初次失败和恢复卸载日志、小型模型配置位于远端 `~/interclarify-archive/maintenance/cache-reclamation-20261019/`；本地保存删除清单、模型/环境来源、验证结果和原日志摘要。旧报告中的资产路径表示实验当时来源，不因删除改写；如需复现退役候选，先按本次inventory和环境清单重建，不把缺失路径当成现役故障。

本轮没有修改运行时或训练代码，没有重跑GPU实验，也不将清理认作训练门禁通过。其他项目、现役prefix和共享包缓存不在删除范围内。
