# comparison实验清理与SoulX重新克隆

2026-11-02。按用户明确指令完成NTF-014，不执行模型推理或训练。

## 清理结果

远端`~/turncontrol-comparison`删除60项顶层实验目录／传输包，文件字节合计7,139,224,041（约7.14GB／6.65GiB），串行操作耗时约194.8秒。文件字节合计不等同于共享文件系统物理空间释放量；原始清单另保存实际空闲空间快照。

删除范围包括`campaigns`、`inspection`、`managers`、`repository`、`runs`、`scripts`、`source`、`submit_logs`、`tmp`及根目录bundle／tar。旧comparison实验仓库和`source/6de0d70`加载器已移除，不再可用。删除前检查所有旧源码worktree，无未提交实现；仅未跟踪的Python字节码缓存作为运行产物清理。

保留公共目录恰为：`cache`、`environment`、`envs`、`models`、`scoring-models`、`upstream`、`wheelhouse`。没有复制或删除公共权重和conda，也没有清理comparison之外的ParaThink历史runs或其他项目。已有ParaThink模型／conda软链接保持可用；旧教师入口属于历史实验，不能再依赖已删除的comparison加载器启动。

操作前后调度队列均为空，未发现comparison后台管理器进程。维护脚本在既有`interclarify-dev` conda运行，限1CPU，串行删除，未占用GPU。

## 官方源码重新克隆

| 项 | 结果 |
| --- | --- |
| 官方来源 | `https://github.com/Soul-AILab/SoulX-Duplug.git` |
| 官方main实测提交 | `a0b9063843df69619b087b95b74597b2176910b8` |
| 本地可浏览入口 | `third_party/soulx-duplug`，Git submodule |
| 远端新checkout | `~/parathink-soulx-duplug/upstream/soulx-duplug` |
| 旧路径形式 | 指向comparison上游快照的符号链接 |
| 新路径形式 | 独立Git目录，来自本次全新clone，无本地修改 |
| `service/model.py` SHA256 | `85d9d049c47d42fda2797806024044d141e2703fd6a63ef2853cbd29887f2a52` |

官方main目前仍为旧冻结提交，因此新克隆和旧快照版本号相同。本次重新获取真实Git仓库，并用父仓库gitlink固定本地版本；未在官方文件上套用旧适配。新源码不调用comparison旧`check_component.py`。后续从该源码开展改造应建立独立工作单，保持可审查diff。

获取父仓库时使用`git clone --recurse-submodules`；已有clone执行`git submodule update --init third_party/soulx-duplug`。子模块类与核心方法见[说明](../../../third_party/soulx-duplug.md)。本次没有安装新依赖、下载模型、启动GPU测试或切换下游Agent。

## 证据与验证

- [删除清单](cleanup_manifest.json)：60项计划与60项完成记录一致，仅剩7个保留目录；远端原文件SHA256为`3107325b8733203308602e65a771d7eeb2609409e6b41e9b0d42a176c43074c4`。
- [克隆与软链替换记录](source_reset.json)：远端原文件SHA256为`c4d5499c393d6b4dc9aba60a2906e746c6c9be6b30aa13d40748da0a6ce9a48f`。两份文件取回后摘要一致。
- 远端完整计划／执行日志／维护脚本位于`~/parathink-soulx-duplug/maintenance/reset-20261102/`。
- 本地子模块Git连通性、干净状态、官方URL／提交号、核心文件摘要检查通过；维护脚本语法及范围拒绝检查通过，未知顶层目录明确失败。
- 旧实验实现与报告的历史结论未因清理改写。项目根入口与远端目录说明已更新，NTF-014完成后归档。
