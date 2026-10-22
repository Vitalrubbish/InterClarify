# X2Q-010 冻结版本 X2-Turn 部署与协议诊断

2026-10-22。状态：环境、权重与 vLLM 服务部署完成；调度单卡作业成功加载状态头并用 dev 输入取得原生 ASR/状态输出。本轮不是正式测试：不计算 WER 或 complete 输出率，不启动回答 LLM/TTS，也不使用上游 `FrameTurnController`。

## 固定版本

| 项目 | 值 |
| --- | --- |
| X2-Turn 源码 | `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5` |
| vLLM | `0.19.1`（wheel，标签 `v0.19.1` = `b1388b1fbf5aaef47937fabe98931211684666a6`） |
| overlay 补丁 | `voxtral-realtime/patches/vllm-voxtral-mtp.patch`（10 个 Python 文件） |
| 模型 | `x-square-robot/X2-Turn-4B-0812`，revision `49c62a9b1170f2ab5168e763b84c2ac5c6b5e1ee` |
| 模型权重 SHA256 | `model.safetensors` = `75c7fd12…6a9117`（HF LFS 摘要核验）；导出 `consolidated.safetensors` = `2450eea56dbf06453a519214e86c27e5ccc09c150f7a0b139deb0828e854eea7` |
| 有效 delay | 480 ms（`tekken.json` 声明 + vLLM tokenizer `get_num_delay_tokens()=6`，12.5 帧/秒、80 ms/帧） |

## 环境与交付方式

独立 conda：`~/miniconda3/envs/interclarify-x2-turn-vllm`（Python 3.11；`vllm==0.19.1`、`torch==2.10.0+cu128`、`transformers==5.5.1`、`mistral_common==1.12.0`、`websockets==17.3`、`soundfile==0.14.0`）。

vLLM 使用官方 wheel，而不是源码构建：源码构建需要完整 CUDA 工具链和远超安装预算的编译资源，且调度节点无法访问 GitHub。为证明 wheel 与固定提交一致，安装阶段用补丁 `index <pre>..` 的 git blob 逐文件核对 wheel，并在临时索引中 `git apply --index` 校验前后置哈希；环境锁记录全部哈希与 `pip freeze`。该差异已在工作单中记录，不宣称等价于源码构建产物。

调度节点无法访问 GitHub，登录节点 git 通道仅约 1.5 KB/s 且不稳定，也没有 scp/sftp。固定源码改为约 640 KB 的离线包（`x2_turn_sources.tar.gz`，SHA256 `73f3883308e5cd558f147a5437619af68b09f608357c094f39052b78e6c3da7c`），经交互 PTY 传入远端。安装与权重下载按用户指示在调试机串行执行；服务启动与诊断在 `vc` 单卡作业中完成。

## 服务配置与结果

调度作业：`pdgpu-4090`，1×RTX 4090（24564 MiB）、8 CPU、32 GiB、单作业上限 4 小时，退出码 0。服务命令要点：`--tokenizer-mode mistral --enforce-eager --gpu-memory-utilization 0.85 --max-model-len 8192`，仅监听 `127.0.0.1:18011`。

| 项目 | 实测 |
| --- | --- |
| 就绪耗时 | 66.1 秒 |
| 权重加载 | 22.96 秒，9.13 GiB |
| 状态头 | 日志出现 `Loaded Voxtral MTP vad_lm_head (idle, noidle, speaking, turn_end, backchannel, uncertain)` |
| KV cache | 10.05 GiB，5,136 tokens，8192 上下文下并发 2.67× |
| GPU 显存峰值 | 20,904 / 24,564 MiB |
| 服务日志中的模型配置 | `max_model_len=8192`；encoder 画像预算 8192 tokens |

dev 输入 `786465049904960526.wav`（16 kHz 单声道，7.8 秒，32-bit float 源文件；客户端按协议转为 PCM16，不重采样）：

- 98 个 80 ms 音频块；发送迟到最大 1.22 ms、平均 0.63 ms。
- 收到 91 帧 `turn.delta`：`idle` 41、`noidle` 4、`speaking` 44、`turn_end` 2；另收到 91 条 `transcription.delta` 并收到完成事件。
- 转写 26 词：`and many pieces and only on a chapter close about connection and improve your chances of moving into a higher education back in your home country`。
- complete 映射以原生 `turn_id=38`/`turn_end` 统计，未改写类别；两帧均在客户端输入结束前到达，输入结束后的 5 秒观察窗内未再出现。该数字只说明协议工作，不是 complete 输出率。

## 失败与修正记录

- `pdcpu` 作业在 GitHub 取源码失败（TLS 中断）；排队也较久。改为离线源码包 + 调试机执行。
- 首次部署：`transformers 5.20.2` 在引擎初始化阶段报 `MistralCommonFeatureExtractor has no attribute fetch_audio`。transformers 5.10 起才引入该调用，vLLM 0.19.1 声明排除 `5.5.0`；固定 `transformers==5.5.1` 后解决。
- 第二次部署：`No available memory for the cache blocks`。encoder 画像是按 `max_model_len=131072` 的最大特征尺寸做的，24 GiB 卡放不下；限制为 8192 后 KV 空间为 10.05 GiB。
- 第三次部署：dev WAV 实际为 32-bit float，`wave` 模块不支持；客户端改用 `soundfile` 转 PCM16。
- 早期安装还修复过 site-packages 路径拼接、镜像 API 需要 User-Agent、重复执行时已打补丁的幂等处理。

失败作业目录（`runs/deploy-20261022-r1/deploy`、`r2`、`r3`）保留在远端，未删除。

## 资源与后续

调试机上环境约 11 GiB、模型（HF + 导出）约 19 GiB、固定数据 61 MiB、源码 8.5 MiB；工作盘当时使用 122 GiB / 1 TiB。安装/导出使用的 CPU 线程为 4，导出阶段峰值内存未单独插桩，调试机当时可用内存约 295 GiB。

证据目录：远端 `interclarify-x2-turn-complete/runs/deploy-20261022-r4/deploy`（`manifest.json`、`service.log`、`readiness.json`、`effective_config.json`、`probe_dev/`、`gpu_samples.csv`、`exit_code.txt`）；锁文件在 `interclarify-x2-turn-complete/env/`。

下一步为 X2Q-014：在同一冻结服务上先跑 5 条冒烟，再执行固定 100 条 test 的正式回放与评分。部署预热与本次 dev 诊断不计入正式分母。
