# 远端前端部署与资产复用

更新：2026-10-29。用户已确认已有 TurnControlComparison 部署可供查找复用。本次先核查资产并建立 ParaThink 独立验证入口，目标为 SoulX-Duplug＋SenseVoiceSmall 能离线加载和执行最小前向；完整 Context、Layer 1/2 与播放接口另行接入，不把组件加载当成整条链路完成。

## 已核查资产

根目录为 `/hpc_stor03/sjtu_home/xuan.zhang/turncontrol-comparison/`，2026-10-29 已登录贵州 HPC 确认目录存在。

| 资产 | 相对路径与版本 |
| --- | --- |
| 共用 conda | `envs/soulx`，Python 3.11；历史记录为 torch/torchaudio 2.6.0+cu126、Transformers 4.52.1、FunASR 1.2.6 |
| SoulX 权重 | `models/soulx-duplug`，revision `61701c4ab8193cc1ee2220d3848872ac6c720142`；包含 GLM 音频 tokenizer、扩词表 Qwen3 与双语状态权重 |
| SenseVoiceSmall | `models/sensevoice-small`，revision `3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`，英文 `language=en` |
| 上游源码 | `upstream/frozen-20261028/soulx-duplug`，提交 `a0b9063843df69619b087b95b74597b2176910b8` |
| 已验证加载器 | `source/6de0d70/scripts/remote/check_component.py`，SHA256 `da9602cf09f30e42cdd9b7f43fd81b7519255bf0eb0161bc4af0372efe0e1901` |

版本来自已有下载 manifest；本次运行保存当前入口摘要和完整包版本，不把历史环境验证当成全环境无依赖冲突的证明。旧环境的推理依赖闭包曾通过，但全局 `pip check` 存在无关克隆包的缺项，本次不修改共享环境。

## 部署方式与验证边界

ParaThink 使用独立根目录 `~/parathink-soulx-duplug/`，源码、提交日志和结果单独存放，模型与 conda 通过软链接只读复用，不重新下载或复制约 8.7GB 的模型文件。FunASR 的离线视图在每次结果目录内建立，避免自动安装依赖或写入共享资产。

[受限入口](../../scripts/remote/run_soulx_frontend_check.md)在同一单卡作业内串行运行两个已有组件检查：SoulX 加载审计与三块 160ms 合成静音前向；SenseVoice 一秒合成静音与固定英文开发音频前八秒识别。静音输出不要求一定为空，英文检查要求非空；不读取 FDB、完整性测试集标签或评分结果，不要求 SoulX 必须输出 complete。

资源为 1×RTX 4090、4 CPU、32GiB RAM，一个 ParaThink 活动作业；单个组件最多 400 秒，整个入口最多 900 秒。继承已验证加载器的 PyTorch 单进程显存比例 0.83，预计约 19.5GiB 分配上限，真实峰值写入结果；启动空闲盘至少 30GiB，单文件上限 128MiB，新增结果／缓存预算 2GiB。资产复用不占用新的模型副本，超时或错误立即退出，不自动重试或扩容。

已有其他项目作业不取消、不改配置。提交前核对调度器 GPU 配额与现有占用；本次只申请一张卡，不继承 TurnControlComparison 多轴并发配置。

## 与 ParaThink 合同的差异

只复用已验证的模型加载与识别入口。TurnControlComparison 的 `speak → replies.start` 映射不进入 ParaThink：这里五类用户状态写入 Context，由 Layer 1 在当前 turn 读取对应 `user_complete` 后生成普通回答；有效用户打断单独直接停止输出。

后续前端适配仍须整理中间转写与修订、保留逻辑话轮和文本版本、发布五类状态及其依据；不能只等服务返回完整文本。此次检查不启动常驻 API，不实现 Context、LLM、TTS、CoT 注入或完整双工播放，也不恢复历史 benchmark。

## 本次实际结果

独立根目录与软链接已建立。冻结入口 `55cc10a` 在单卡作业 `job-179328001617494954185-xuan-zhang` 上完成，两个组件通过，退出码 0：SoulX 加载与三块静音前向耗时 72.10 秒，PyTorch 峰值分配／保留为 4.64／4.76GiB；SenseVoice 检查耗时 19.26 秒，英文 dev 识别非空。耗时包含加载，不作为在线延迟。收尾核对作业已不在活动列表，源码与单次结果约 43KiB、107KiB。

权重审计无缺失键，唯一额外嵌入别名与实际权重一致。SenseVoice 静音输入返回 `Yeah.`，按原始事实保留，不据此宣称静音无误识别。完整版本、包清单、配置、日志与边界见[实际报告](../../../reports/soulx/20261029-frontend-deployment/README.md)。基础部署通过，尚未启动常驻服务或实现 Context、五状态输入及播放接口。工作单仅按用户明确指令建立，本次不自行创建 issue。
