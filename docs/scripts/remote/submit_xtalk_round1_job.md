# `scripts/remote/submit_xtalk_round1_job.sh`

## 整体作用

把首轮验收作业提交到 SJTU 集群 `pdgpu-4090` 队列的薄封装，使用由 [build_xtalk_round1_image.sh](build_xtalk_round1_image.sh) 构建、基于已有 `xtalk:v0.17` 的首轮镜像（CUDA 12.8.1 + conda + ffmpeg + vLLM 0.16.0）。

默认镜像为 `sjtu_yukai-xuanzhang-xtalk-round1:v0.3`，与当前 `flash_attention_2` 配置一致（v0.3 在 MOSS 环境加入 flash-attn wheel；v0.2 不含，会导致 TTS 依赖检查失败）。`XTALK_ROUND1_IMAGE` 仍可覆盖。

## 用法与资源

```bash
bash scripts/remote/submit_xtalk_round1_job.sh asr       # 1 GPU /  8 CPU /  32G
bash scripts/remote/submit_xtalk_round1_job.sh services  # 4 GPU / 32 CPU / 128G
bash scripts/remote/submit_xtalk_round1_job.sh chain     # 4 GPU / 32 CPU / 128G
```

- `asr`：三档 ASR 解码窗口 smoke（对应任务单第 4 节）。
- `services`：三服务启动、验证、上游测试与 TTS 冷/热态（对应任务单第 5、6 节）。
- `chain`：完整路径 ASR → LLM → TTS，测各阶段延迟与输出内容；日志同时复制到仓库根目录 `data/runs/<tag>/`（已 gitignore）。

提交日志写入 `$XTALK_ROUND1_ARTIFACT_ROOT/submit_logs/`；跟踪方式为 `vc list -j <JOBID>` 与 `vc logs -t <TASKID>`。镜像、作业名、各模式 GPU 数可用环境变量覆盖，实际作业命令委托给 `run_xtalk_round1_node_job.sh`。
