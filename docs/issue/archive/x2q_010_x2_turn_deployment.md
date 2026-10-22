# X2Q-010：部署冻结版本 X2-Turn 流式服务

状态：已完成并归档（2026-10-22）。依赖：[X2Q-008](x2q_008_complete_protocol.md)；真实音频预热依赖 [X2Q-009](x2q_009_fleurs_data.md) 的 dev 输入。依据：[测试计划](../../dev/X2-Turn/complete_test_on_fleurs.md)。

## 目标与工作内容

在远端隔离 conda 部署原始 ASR/状态双头服务，为两类指标提供真实输出。

- 固定 X2-Turn `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5` 和作者 vLLM 0.19.1 overlay 基线 `b1388b1fbf5aaef47937fabe98931211684666a6`。
- 下载 `x-square-robot/X2-Turn-4B-0812`，锁定实际 HF revision、tokenizer、导出配置与权重哈希，不额外下载无关变体。
- 确认状态头已加载、服务端有效 delay=480 ms；客户端报告字段不能替代有效配置检查。
- 提供原始文本 delta、状态 delta 和完成事件，核对 `turn_end` / ID38 对应 complete，其余类别/概率也保留。
- 绕开演示能量门、idle 文本抑制和 `FrameTurnController`，不启动回答 LLM/TTS。
- 在调度 GPU 上用独立 dev 完成加载/预热与协议诊断，失败留账、预热不计分。

## 交付

拟由 `scripts/remote/run_x2_turn_complete_job.sh` 管理服务生命周期，镜像说明为 `docs/scripts/remote/run_x2_turn_complete_job.md`，解释入口、阶段、参数和清理方法。远端保存模型/环境/源码锁、有效配置、日志与预热证据。

## 实施记录

2026-10-22 启动。预检确认：远端登录节点可连，旧 X2 模型与环境已清理，`interclarify-x2-turn-complete/dataset` 的固定 FLEURS 子集完好，`pdcpu` 与 GPU 分区可用，`pypi.org` 与 `conda.anaconda.org` 直连不可用，清华 PyPI/conda 镜像、`hf-mirror.com` 可用。

网络限制（实测）：调度节点完全无法访问 `github.com`（TLS 连接被中断）；登录节点 git 数据通道约 1.5 KB/s 且不稳定，`raw.githubusercontent.com` 不可达，codeload 约 115 KB/s；无 scp/sftp 通道。因此固定源码改为在有 GitHub 访问的机器上构建约 640 KB 的源码包，经交互 PTY 传入远端，再由安装阶段离线校验。

本轮确定：

- 模型固定 revision `49c62a9b1170f2ab5168e763b84c2ac5c6b5e1ee`，仓库自带 `params.json` 与 `tekken.json`，不额外下载基底模型。
- 有效延迟 480 ms 的来源为 `tekken.json` 的 `audio.transcription_delay_ms`、`frame_rate=12.5`（6 × 80 ms）。服务作业用 vLLM 自己的 `MistralTokenizer` 读取 `get_num_delay_tokens()` 复核，不用客户端字段。
- vLLM 采用官方 `0.19.1` wheel 加作者 overlay：源码构建超出安装预算且调度节点无法取源码。wheel 中 10 个待改文件的 git blob 必须等于补丁 `index <pre>..` 前置哈希，补丁在临时索引中用 `git apply --index` 应用并核对后置哈希；环境锁记录全部哈希。该差异已记录，不宣称等价于源码构建产物。
- 安装与权重下载在调试机上串行执行（调试机可用内存约 295 GiB、80 核、922 GiB 空闲）；服务启动与协议诊断仍在 `vc` 单卡作业中执行。

入口：`build_x2_turn_source_bundle.py`、`setup_x2_turn_vllm_env.sh`、`prepare_x2_turn_model.py`、`x2_turn_service_probe.py`、`run_x2_turn_complete_job.sh`、`submit_x2_turn_complete_jobs.sh`，说明见 `docs/scripts/remote/` 同名文档。

结果（2026-10-22）：`vc` 单卡 4090 作业退出码 0，服务 66.1 秒就绪，日志确认状态头加载；有效 delay 480 ms 由 vLLM tokenizer 复核（6 tokens × 80 ms）。dev 输入收到 91 条 `transcription.delta` 与 91 帧 `turn.delta`（idle 41、noidle 4、speaking 44、turn_end 2），`turn_id=38`/`turn_end` 映射成立；complete 帧均在输入结束前到达，观察窗内未再出现。权重加载 22.96 秒、9.13 GiB，GPU 峰值 20,904/24,564 MiB，KV 10.05 GiB。完整证据与失败修正见[部署报告](../../reports/x2_turn_complete/20261022-deploy/README.md)。

执行偏差：安装与权重下载按用户指示在调试机执行，未放入 `pdcpu` 作业；安装/导出阶段的峰值内存未单独插桩，调试机当时可用内存约 295 GiB。其余资源上限与“失败不自动加卡”的要求保持。

## 验收

- [x] 独立 conda 可复现，未覆盖现役 ASR/TTS/评分环境。
- [x] 真实服务输出 ASR 和原生状态，验证 complete 映射与有效 delay。
- [x] 推理仅通过 vc，最多 1×24 GiB GPU、8 CPU、32 GiB RAM、单作业 4 小时；安装/下载最多 4 CPU、16 GiB RAM、并发 2（执行位置按用户指示改为调试机）。
- [x] 保存资源峰值并遵守整轮磁盘预算，失败不自动加卡或无限重试。

服务启动或预热成功不等于正式测试完成。
