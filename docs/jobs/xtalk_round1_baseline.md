# 任务单：首轮 Qwen ASR + MOSS TTS 模型服务验收

## 目标与当前阻塞

首轮组合：Qwen3-ASR 1.7B、Qwen/Qwen3-8B-AWQ（2026-10-09 由部署示例的 30B-A3B AWQ 变更为本地已验证的 8B AWQ，依据 [xtalk_baseline_stack.md](../xtalk_baseline_stack.md) 的变更记录；参考系统 DuplexCascade 的 LLM 为 7B 级）、MOSS-TTS-Realtime + MOSS-Audio-Tokenizer、XTurnix-ZH Base。System Backchannel 关闭，Layer 0 移除。先验收模型服务，再补齐 ASR 接入并运行原生 X-Talk 基线；尚不实现 micro-turn 控制层或 InterClarify。

当前 X-Talk `Qwen3ASRClient` 与其 ASR 抽象不匹配，不能直接用作完整链路。下面的 ASR 测试调用官方 API；禁止把准备 YAML 当成 `Xtalk.from_config` 的服务配置。该适配缺口须由后续 A0 接入工作补齐，完整音频闭环和 FDB 仍待完成。

## 1. 远端目录与资源

准备工作可在允许下载与安装的节点执行；所有 GPU 推理必须在已申请的计算节点或作业内执行。沿用 `pdgpu-4090` 队列和项目现有 `vc`/平台申请方式。完整分服务验证建议 4 张 24 GB 4090、32 CPU、128 GB 内存；单模型 smoke 可申请 1 张卡，并传 `--gpu-index 0`。资源为起始建议，显存实测后再调整。

先在远端终端设置路径：

```bash
export INTERCLARIFY_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/InterClarify
export XTALK_ROUND1_ROOT=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1
export XTALK_ROUND1_MODEL_ROOT="$XTALK_ROUND1_ROOT/models"
export XTALK_ROUND1_ARTIFACT_ROOT="$XTALK_ROUND1_ROOT/artifacts"
export XTALK_MOSS_SERVICE_ROOT="$XTALK_ROUND1_ROOT/moss-service"
export XTALK_MOSS_SOURCE_ROOT="$XTALK_ROUND1_ROOT/moss-source"
export HF_ENDPOINT=https://hf-mirror.com
export PYTHONNOUSERSITE=1
mkdir -p "$XTALK_ROUND1_ROOT" "$XTALK_ROUND1_ARTIFACT_ROOT"
git -C "$INTERCLARIFY_ROOT" pull --ff-only
```

当前远端账号/共享存储若不同，修改这些根路径。模型、源码服务与 InterClarify 各自独立，不放入 `3rd-party`。已有 checkout 有本地改动时先保存，使用新的目录克隆，避免覆盖。

## 2. 固定四份源码并构建验收镜像

准备阶段在允许下载与安装的节点执行；目录已存在时先检查提交和工作树。X-Talk 使用已关联 fork 的原生固定提交。除源码外不再手工创建 conda 环境：首轮验收统一运行 `sjtu_yukai-xuanzhang-xtalk-round1` 镜像，它**直接基于已有 `xtalk:v0.17` 镜像**（CUDA 12.8.1 + conda + ffmpeg + vLLM 0.16.0 已就绪，不重建迭代链）；LLM 与 turn detector 复用基座 base 环境，另用**一个合并层**建好四个 `xtalk-round1-*` 环境（ASR 因 `qwen_asr` 不兼容 vLLM 0.16 而保留独立 0.14.0 环境）。

```bash
bash "$INTERCLARIFY_ROOT/scripts/remote/setup_xtalk_round1_env.sh"
```

`setup_xtalk_round1_env.sh` 幂等地克隆并固定四份源码、创建四个环境并安装依赖（git 不可达时允许 `PINNED_UPSTREAM_COMMIT` 标记的 tarball 导入树）。构建主机上打镜像时，wheelhouse 作为本地缓存（`--find-links`），其余依赖走 pypi.org；可先用 `fill_wheelhouse_round1.sh` 预填缓存，再构建并推送镜像：

```bash
bash "$INTERCLARIFY_ROOT/scripts/remote/fill_wheelhouse_round1.sh"
PUSH=1 bash "$INTERCLARIFY_ROOT/scripts/remote/build_xtalk_round1_image.sh"
```

`fill_wheelhouse_round1.sh` 用集群可达镜像补齐 `wheels/`（初次 `pip download` 漏掉了 `compressed-tensors` 等 vLLM 依赖）；`build_xtalk_round1_image.sh` 用 BuildKit named contexts 把 `wheels/` 与源码树作为构建上下文，wheel 仅 bind-mount 参与构建、不进入镜像层。使用集群可达的 conda/PyPI 镜像，不要执行 MOSS 封装的 `install.sh` / `start.sh`（它们使用 `.venv`），本任务由项目启动脚本直接在镜像 conda 环境调用其 Python 入口。

MOSS 固定源码要求 torch/torchaudio `2.9.1+cu128`、Transformers `5.0.0`；Qwen 固定源码要求 vLLM `0.14.0`、Transformers `4.57.6`。GPU 驱动需支持相应 CUDA，MOSS 要求 CUDA 12.8，FFmpeg 需可用。候选依赖尚未运行冻结，安装后记录完整版本与测试结果；不在同一环境混装 Qwen 与 MOSS 的推理栈。

镜像内环境可用如下方式归档到共享产物目录，避免依赖登录节点环境（LLM/turn detector 用镜像 base 环境）：

```bash
docker run --rm -v "$XTALK_ROUND1_ARTIFACT_ROOT:/artifacts" "$XTALK_ROUND1_IMAGE" bash -lc '
  for env in base xtalk-round1-tools xtalk-round1-asr xtalk-round1-moss xtalk-round1-client; do
    /opt/conda/bin/conda run -n $env python -m pip freeze > /artifacts/$env.pip.txt
    /opt/conda/bin/conda list -n $env --explicit > /artifacts/$env.conda.txt
  done'
```

节点作业脚本在计算节点内运行 `nvidia-smi` 并写入产物目录；不能把登录节点的无 GPU 结果当成模型失败。

## 3. 下载并锁定五组权重

```bash
conda run --no-capture-output -n xtalk-round1-tools python \
  "$INTERCLARIFY_ROOT/scripts/remote/run_xtalk_round1.py" \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" download
```

首次把各模型 ID 解析为不可变 revision，写入 `models.lock.json` 后下载；后续复用这些 revision。HF 镜像缺少某个 revision 时保留锁定文件并恢复官方 endpoint/下载通道，不换成浮动 `main`。TTS 必须同时下载 codec。准备一份可用于测试的中文参考音色，以及日期/时间、人名、自然停顿、改口、中英混说的 16 kHz 单声道 WAV，放在 `$XTALK_ROUND1_ROOT/audio/`；记录来源与人工文本，权重和音频不提交 Git。

## 4. 先跑独立 ASR（计算节点）

```bash
conda run --no-capture-output -n xtalk-round1-asr python \
  "$INTERCLARIFY_ROOT/scripts/remote/run_xtalk_round1.py" \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" asr-smoke \
  --audio "$XTALK_ROUND1_ROOT/audio/request.wav" \
  --output "$XTALK_ROUND1_ARTIFACT_ROOT/asr-06" --chunk-seconds 0.6
```

默认使用已分配四卡中的逻辑 GPU 2；单卡作业追加 `--gpu-index 0`。分别重跑 `--chunk-seconds 1.2` 和 `2.0`，使用 `asr-12`、`asr-20` 等新输出目录。脚本按 80 ms 步长原速输入，记录首 partial、文本修订、纯解码 RTF 与最终转写。0.6 秒是内部解码窗口试验值，不是已保证的首字延迟。

在集群上提交单卡作业自动跑完三档窗口（`run_xtalk_round1_node_job.sh asr` 内部按 0.6/1.2/2.0 顺序调用上述命令并归档）：

```bash
bash "$INTERCLARIFY_ROOT/scripts/remote/submit_xtalk_round1_job.sh" asr
```

## 5. 启动三个服务并验证

在同一四卡计算节点的三个终端分别执行，保留进程前台运行；或按集群允许方式管理同一作业内的服务。所有命令都从已分配设备列表选择卡，禁止在登录节点直接启动推理。

```bash
bash "$INTERCLARIFY_ROOT/scripts/remote/start_xtalk_round1_service.sh" llm
bash "$INTERCLARIFY_ROOT/scripts/remote/start_xtalk_round1_service.sh" turn_detector
bash "$INTERCLARIFY_ROOT/scripts/remote/start_xtalk_round1_service.sh" tts
```

上述三行各自占用一个终端，不应在同一终端顺序执行。默认为逻辑 GPU 0/1/3，端口 8000/8003/8004；单服务作业追加 `--gpu-index 0`。首轮 TTS 并发为 1，模型和 codec 同卡。若 24 GB OOM，保存日志和显存，不根据封装仓库中 48 GB 改装卡的报告推定我们也能运行。

集群上由单个四卡作业自动完成本节与第 6 节：`run_xtalk_round1_node_job.sh services` 在后台启动三个服务、等待端点就绪、抓取 `/v1/models` 与流式补全、跑 XTurnix 适配器探针与上游 pytest、再执行 TTS 冷/热/双流 smoke，最后统一写入 `$XTALK_ROUND1_ARTIFACT_ROOT/services/<时间戳>/`。

```bash
bash "$INTERCLARIFY_ROOT/scripts/remote/submit_xtalk_round1_job.sh" services
vc list -j <JOBID>
vc logs -t <TASKID>
```

在同节点另一个终端检查模型与 TTS 服务：

```bash
curl --fail http://127.0.0.1:8000/v1/models
curl --fail http://127.0.0.1:8003/v1/models
curl --fail http://127.0.0.1:8004/health

curl --fail http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"xtalk-round1-llm","messages":[{"role":"user","content":"请用一句话介绍自己。"}],"temperature":0,"max_tokens":64,"stream":true}'
```

轮次模型必须显示服务名 `xturnix`。进一步用 X-Talk 的现有 XTurnix 测试/适配器验证 keep/start/stop，不仅检查 `/v1/models`。X-Talk 客户端环境先运行上游测试；缺少可选依赖的失败和需要真实服务的测试分别记录，不把未运行项报告为通过。

```bash
cd "$XTALK_ROUND1_ROOT/xtalk"
conda run --no-capture-output -n xtalk-round1-client python -m pytest tests/test_moss_tts_realtime.py -q
conda run --no-capture-output -n xtalk-round1-client python -m pytest -q
```

## 6. MOSS 冷启动、热态和增量输出

参考音频路径必须同时对客户端与 TTS 服务可见。服务输出固定 48 kHz，与当前 `MossTTSRealtime` 适配器匹配。

```bash
conda run --no-capture-output -n xtalk-round1-client python \
  "$INTERCLARIFY_ROOT/scripts/remote/run_xtalk_round1.py" \
  --model-root "$XTALK_ROUND1_MODEL_ROOT" tts-smoke \
  --reference "$XTALK_ROUND1_ROOT/audio/reference.wav" \
  --output "$XTALK_ROUND1_ARTIFACT_ROOT/tts-cold"
```

同一服务进程再跑一次，改用 `tts-warm`；需要观察双流时增加 `--gap-seconds 2` 并使用新的目录。首轮编译可能数分钟，不提前把冷启动判断为稳态延迟。检查 `tts.wav`、`first_audio_seconds`、`audio_seconds`、`audio_before_flush` 和实际采样率；热态应验证 flush 前已有音频输出。音质、日期时间读法和停播仍需试听/交互验收，`COMPLETE` 只表示独立请求执行完成。

## 7. 回传与下一步

回传 `models.lock.json`、五份 conda/pip 记录、源码提交、GPU/驱动信息、ASR 三档窗口报告及对应事件、TTS 冷/热态报告与样本、服务日志和上游测试结果。人工核对日期/时间与人名，报告前缀稳定性、首包、积压和峰值显存。

这些结果通过后，补齐 Qwen ASR 的会话隔离、累计前缀/修订、临时 final 语义与 reset/clone 适配，生成可运行的 X-Talk 全链路配置，再进行音频闭环、用户附和、有效插话和 FDB smoke。完成上述冻结门禁后，才开始无 System Backchannel 的控制层改造。
