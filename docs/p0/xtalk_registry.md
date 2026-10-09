# X-Talk 参考底座登记（P0）

## 固定来源

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/xcc-zach/xtalk |
| 起始提交 | `5f0d9959edf1026588246efbed827b078cbb114c` |
| 提交日期 | 2026-10-03 |
| 集群基础镜像 | `docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk:v0.17` |
| Python 要求 | `>=3.10` |

该提交只是路线重置时的固定起点。P1 开始前应确认是否采用此提交、内部 fork 的对应提交，或经评审后的更新版本；一旦开始实验不得追踪浮动 `main`。

## 采用原因

X-Talk 已提供模块化 ASR、LLM agent、TTS、VAD/turn detector、EventBus、会话服务、TTS 协调和播放管理，适合通过扩展 manager、event 和 model slot 实现 InterClarify 所需行为。项目不再复制 DuplexCascade 的源码和权重，而把其能力拆成可测试目标。

## 必须核验的事项

1. **镜像与源码对应关系**：`v0.17` 标签尚不能证明包含哪个 Git 提交。P1 任务必须记录镜像 digest、镜像内安装包版本和源码提交。
2. **许可证元数据差异**：固定提交的根目录 `LICENSE` 是 Apache-2.0，但 `pyproject.toml` 的 license 字段写为 MIT。使用或分发前必须以项目方说明和实际依赖许可证审计为准，并记录结论。
3. **optional extras**：X-Talk 不同 ASR、TTS、turn detector 和本地 LLM 使用不同依赖与许可证。只安装实验实际需要的 extras。
4. **接口稳定性**：上游声明仍处于 active prototyping。所有扩展点以固定提交为准，升级前重新运行差距审计和回归测试。
5. **模型来源**：ASR、TTS、LLM agent 和 turn detector 尚未固定。任何权重都必须记录来源、revision、校验值和访问条件。

## 集成策略

- 首选独立固定 checkout 或项目 fork，通过可编辑安装进入 conda 环境；
- InterClarify 扩展放在 `src/interclarify/xtalk/`，通过公开事件和 manager 接口接入；
- 若必须修改 X-Talk 上游文件，补丁需记录文件、原因、上游提交和对应测试；
- 不在未核验来源前把整个 X-Talk 仓库复制到 `3rd-party/`；
- 不创建第二套 EventBus、会话服务或 TTS 播放队列。

## 功能对齐范围

需要在 X-Talk 上验证或补齐的行为是持续监听、micro-turn、backchannel、提前回答、用户打断停播、单一输出仲裁、单一播放所有权和完整事件时间线。DuplexCascade 仅作为这些行为的相关工作参照。
