# X2Q-010：部署冻结版本 X2-Turn 流式服务

状态：进行中（2026-10-22 启动）。依赖：[X2Q-008](archive/x2q_008_complete_protocol.md)；真实音频预热依赖 [X2Q-009](x2q_009_fleurs_data.md) 的 dev 输入。依据：[测试计划](../dev/X2-Turn/complete_test_on_fleurs.md)。

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

2026-10-22 启动。预检确认：远端登录节点可连，旧 X2 模型与环境已清理，`interclarify-x2-turn-complete/dataset` 的固定 FLEURS 子集完好，`pdcpu` 与 GPU 分区可用，`pypi.org` 与 `conda.anaconda.org` 直连不可用，清华 PyPI/conda 镜像与 `hf-mirror.com`、`github.com` 可用。

本轮确定：

- 模型固定 revision `49c62a9b1170f2ab5168e763b84c2ac5c6b5e1ee`，仓库自带 `params.json` 与 `tekken.json`，不额外下载基底模型。
- 有效延迟 480 ms 的来源为 `tekken.json` 的 `audio.transcription_delay_ms`、`frame_rate=12.5`（6 × 80 ms），部署作业会用 `mistral-common` 的 `get_num_delay_tokens()` 复核，不用客户端字段。
- vLLM 采用官方 `0.19.1` wheel 加作者 overlay：源码构建超出安装阶段 4 CPU / 16 GiB 预算且需要完整 CUDA 工具链。安装脚本先逐文件核对 wheel 与固定提交 `b1388b1` 的 10 个 Python 文件哈希，不一致即中止，全部哈希写入环境锁。该差异已记录，不宣称等价于源码构建产物。
- 安装/下载放入 `pdcpu` 作业，推理仍在单卡 24 GiB 作业中执行。

入口：`setup_x2_turn_vllm_env.sh`、`prepare_x2_turn_model.py`、`x2_turn_service_probe.py`、`run_x2_turn_complete_job.sh`、`submit_x2_turn_complete_jobs.sh`，说明见 `docs/scripts/remote/` 同名文档。远端结果待作业完成后补充。

## 验收

- [ ] 独立 conda 可复现，未覆盖现役 ASR/TTS/评分环境。
- [ ] 真实服务输出 ASR 和原生状态，验证 complete 映射与有效 delay。
- [ ] 推理仅通过 vc，最多 1×24 GiB GPU、8 CPU、32 GiB RAM、单作业 4 小时；安装/下载最多 4 CPU、16 GiB RAM、并发 2。
- [ ] 保存资源峰值并遵守整轮磁盘预算，失败不自动加卡或无限重试。

服务启动或预热成功不等于正式测试完成。
