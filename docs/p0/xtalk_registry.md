# X-Talk 参考底座登记（P0）

## 固定来源

| 项 | 值 |
| --- | --- |
| 项目 fork | https://github.com/Vitalrubbish/xtalk |
| 官方 upstream | https://github.com/xcc-zach/xtalk |
| 起始提交 | `5f0d9959edf1026588246efbed827b078cbb114c` |
| 提交日期 | 2026-10-03 |
| 集群基础镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk:v0.17` |
| Python 要求 | `>=3.10` |

本地 fork、项目 fork `origin/main` 与官方 `upstream/main` 在登记时均指向该提交。开始实验后以具体提交为准，不追踪浮动 `main`。

## 采用原因

X-Talk 已提供模块化 ASR、LLM agent、TTS、VAD/turn detector、EventBus、会话服务、TTS 协调和播放管理。第一阶段在项目 fork 中先实现 DuplexCascade 风格的通用双工能力；底座稳定后，InterClarify 再通过公开扩展接口加入 Layer 2。

## 必须核验的事项

1. **镜像与源码对应关系**：`v0.17` 标签尚不能证明包含哪个 Git 提交。P1 任务必须记录镜像 digest、镜像内安装包版本和源码提交。
2. **许可证元数据差异**：固定提交的根目录 `LICENSE` 是 Apache-2.0，但 `pyproject.toml` 的 license 字段写为 MIT。使用或分发前必须以项目方说明和实际依赖许可证审计为准，并记录结论。
3. **optional extras**：X-Talk 不同 ASR、TTS、turn detector 和本地 LLM 使用不同依赖与许可证。只安装实验实际需要的 extras。
4. **接口稳定性**：上游声明仍处于 active prototyping。所有扩展点以固定提交为准，升级前重新运行差距审计和回归测试。
5. **模型来源**：ASR、TTS、LLM agent 和 turn detector 尚未固定。任何权重都必须记录来源、revision、校验值和访问条件。

## 集成策略

- X-Talk fork 与 InterClarify 保持独立 Git 仓库，不使用子模块；
- 本地 `InterClarify/xtalk/` 仅作为工作区 checkout，并由 InterClarify `.gitignore` 排除；
- 通用 DuplexCascade 功能直接在 X-Talk fork 中实现和测试；
- InterClarify 只记录 X-Talk fork 提交，并在后续通过稳定扩展接口接入；
- 修改 X-Talk 核心文件时记录原因、upstream 基线和对应测试；
- 不创建第二套 EventBus、会话服务或 TTS 播放队列。

## 功能对齐范围

阶段 A 先跑通并冻结第一套原生组合，再补齐持续监听、micro-turn、Layer 1、提前回答、用户附和识别、用户打断停播、单一输出仲裁、单一播放所有权和完整事件时间线。当前移除 Layer 0，目标为 DuplexCascade 无 System Backchannel 版本；阶段 B 才由 InterClarify 加入主动澄清。组件候选和冻结状态见 [../xtalk_baseline_stack.md](../xtalk_baseline_stack.md)。
