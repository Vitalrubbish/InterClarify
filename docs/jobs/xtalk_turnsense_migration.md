# 任务单：首轮 turn detector 迁移到 TurnSense

## 背景

T3/T4 联调暴露出两个阻塞：一是 TTS 服务启动偶发卡住（单独处理），二是 **headless 回放里话轮永不结束**（`finish_asr=null`、`tts_audio_bytes=0`）。定位结论：不是框架 bug，而是 **turn detector 的选择 + 输入语言** 的问题。

- 原配置用 `XTurnix`（`xcczach/xturnix-zh-base`），它是**纯文本**检测器：`xturnix.py` 里 `del audio`，只根据 ASR 文本 + 状态给出 `<|start|>/<|keep|>/<|stop|>`。
- 首轮输入 `audio/request.wav` 是**英文**（ASR 转写 “Please tell me a very long and detailed story about a dragon.”）。
- 本地 CPU 复现（transformers 4.57.6 + 该模型权重，复刻其 `turn_pipeline.py` 的 prompt/约束）确认：

  | 输入 | 状态 | 输出 |
  | --- | --- | --- |
  | 英文 request | listening | `<|keep|>`（start 0.14 / keep 0.86） |
  | 中文问句 | listening | `<|start|>`（start 0.92） |
  | 中文请求 | listening | `<|start|>`（start 0.76） |

  即英文样例被判 keep；再叠加 `xturnix.py` 在末尾 pause 处 `reuse_previous` 复用 pause 前的 keep，话轮永不 `START_GENERATION`。
- `TurnSense` 是**音频**检测器（`turn_sense.py` 缓存 PCM 帧、POST 到 `/infer/bytes`，按 `complete/incomplete/invalid` 判定，`del text`），与语言无关。本地实测英文 request → `complete` 0.93。

因此决定：**首轮 turn detector 从 XTurnix 切换为 TurnSense**，与早先的复现保持一致。

## 变更

- **配置** `configs/xtalk_round1.yaml`：`models` 移除 `turn_detector`（不再是 HF snapshot）；`environments.turn_detector = xtalk-round1-turnsense`；`services.turn_detector` 改为 TurnSense 描述（`kind`、`source_dir`、`onnx_file`/`cmvn_file` 及 sha256、`upstream_repo`/`upstream_commit`、`clip_mode`、`max_concurrency`/`max_workers`、`use_cuda`）；`dependency_candidates` 增加 `turnsense_onnxruntime`/`turnsense_kaldi_native_fbank`。
- **运行配置** `configs/xtalk_round1_runtime.json`：`turn_detector.type` 由 `XTurnix` 改为 `TurnSense`（`base_url=http://127.0.0.1:8003`）。
- **编排脚本** `scripts/remote/run_xtalk_round1.py`：`serve turn_detector` 启动 vendored TurnSense `service.py`（不再 `vllm serve`），支持 `XTALK_TURNSENSE_PYTHON` 用绝对解释器启动；`check-deps` 增加 `turn_detector` 角色（校验 onnxruntime / kaldi-native-fbank）。
- **节点作业** `scripts/remote/run_xtalk_round1_node_job.sh`：就绪检查改 `/healthz`；`dependency_check`/`env_imports` 覆盖 turnsense 环境（绝对路径）；`xturnix_adapter_probe` 换成 TurnSense 探针（要求 request.wav → `complete`）；`link` 模式不再传 `--drop-turn-detector`。
- **镜像** `scripts/remote/Dockerfile.round1`：新增 `xtalk-round1-turnsense` 环境与 `COPY scripts/remote/turnsense /opt/src/xtalk-TurnSense`（供下次构建；当前运行改用共享 home 上的同名环境）。
- **vendored 服务** `scripts/remote/turnsense/`：上游 <https://github.com/xcc-zach/xtalk-TurnSense> @ `cc0681c85771117958785faf3d6a7f402018a83e`，见 [turnsense/README.md](../scripts/remote/turnsense/README.md)。
- **文档**：本任务单；`docs/configs/xtalk_round1*.md`、`docs/scripts/remote/run_xtalk_round1*.md`、`docs/scripts/remote/Dockerfile.round1.md`、`docs/jobs/xtalk_round1_followup.md` 同步更新。

## 资产与置备

- 模型：`model_int8.onnx`（sha256 `d5105b9a…a5e4c`）+ `am.mvn`（sha256 `29b3c740…96ae5`），放在 `$XTALK_ROUND1_MODEL_ROOT/turnsense/`。
- 环境 `xtalk-round1-turnsense`（共享 home，用 conda 创建）：`numpy==2.2.6`、`librosa==0.11.0`、`soundfile==0.13.1`、`kaldi-native-fbank==1.22.3`、`fastapi==0.116.1`、`uvicorn[standard]==0.35.0`、`python-multipart==0.0.20`、`onnxruntime==1.23.2`、`PyYAML==6.0.3`。
- 本地验证：`serve turn_detector` 起服务后 `/healthz` ok，`POST /infer/bytes` 英文 request → `complete`。

## 验证步骤

```bash
# 本地/登录节点验证服务
bash scripts/remote/submit_xtalk_round1_job.sh link        # 完整联调
bash scripts/remote/submit_xtalk_round1_job.sh services    # 服务与探针
```

期望：`link_report.json` 出现 `finish_asr`、`update_resp`/`finish_resp` 与 TTS 音频（`tts_audio_bytes>0`），`response_finished=true`。

## 已知限制

- `xtalk-round1-turnsense` 目前建在共享 home，未烘进 v0.3 镜像；node job 用 `XTALK_TURNSENSE_PYTHON` 绝对路径调用。下次镜像构建（`Dockerfile.round1`）会把它烘进去，届时可去掉该覆盖。
- TurnSense 默认 CPU 推理（200 ms 周期 + 8 并发足够）；如与其它服务争卡需改 `use_cuda: true` 并安装 `onnxruntime-gpu`。
- fork 中的 XTurnix 适配器保留（仍受支持），只是首轮不再使用；`<|pause|>` 等 token 的语义不再影响首轮链路。
