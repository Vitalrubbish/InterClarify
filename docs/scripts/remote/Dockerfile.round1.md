# `scripts/remote/Dockerfile.round1`

## 整体作用

首轮 X-Talk 模型服务验收的集群运行镜像。**直接基于已有的 `xtalk:v0.17` 镜像**（CUDA 12.8.1 + conda + ffmpeg + sudo + vLLM 0.16.0），不再经过 P0 中间镜像，也不重建 X-Talk 迭代链。LLM 与 turn detector 复用基座 base 环境，另外**用一个合并层**建好四个 round-one conda 环境。

## 构建方式

构建由 [build_xtalk_round1_image.sh](build_xtalk_round1_image.md) 封装，使用 BuildKit 的 **named build contexts**，避免把 `$XTALK_ROUND1_ROOT` 下的模型缓存和产物当作普通构建上下文发送：

```bash
PUSH=1 bash scripts/remote/build_xtalk_round1_image.sh
```

等价的手工命令：

```bash
DOCKER_BUILDKIT=1 docker build -f scripts/remote/Dockerfile.round1 \
  --build-context wheels=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/wheels \
  --build-context qwen-asr=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/qwen-asr \
  --build-context moss-source=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/moss-source \
  --build-context xtalk=/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1/xtalk \
  -t docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.1 \
  /hpc_stor03/sjtu_home/xuan.zhang/InterClarify
docker push docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-round1:v0.1
```

## 设计要点

- **精简层数**：`FROM .../xtalk:v0.17`，把三份固定源码树合并成一个 `COPY` 层；wheelhouse 与源码树都通过 named context 提供，`wheels/` 仅以 `RUN --mount=type=bind` 挂载参与构建，约 6 GB wheel 不会进入镜像层。
- **基座环境复用**：LLM（Qwen3-8B-AWQ）与 turn detector 直接使用镜像 base 环境自带的 **vLLM 0.16.0 + torch 2.9.1+cu128**，不再单独建 `xtalk-round1-vllm` 环境。
- **ASR 独立环境（vLLM 0.14.0）**：`qwen_asr` 的多模态 processor 仍覆写 `BaseMultiModalProcessor._get_data_parser`，该接口在 vLLM 0.16 已迁移到 `BaseProcessingInfo.build_data_parser`，实测在 base 环境直接报错，因此 ASR 必须保留 vLLM 0.14.0 + transformers 4.57.6 的独立环境。MOSS 环境单独装 torch/torchaudio 2.9.1+cu128 + transformers 5.0.0，互不混装；环境名与共享存储版相同（`xtalk-round1-*`），作业脚本无需区分。
- **wheelhouse 作为本地缓存**：构建先 `--find-links /wheelhouse` 命中已下载的大 wheel（torch cu128、vllm、transformers），其余依赖从 `pypi.org` 拉取（阿里云镜像对个别 wheel 会卡死）；安装后的真实版本由任务单第 7 节归档冻结。
- **editable 源码打入镜像**：qwen-asr、moss-source、xtalk 以 editable 方式安装自 `/opt/src/`，其固定提交与配置 `sources` 一致；`--no-build-isolation` 保证不额外拉取构建后端，`setuptools` 先显式安装。
- conda 环境创建走清华 tuna anaconda 镜像加速；构建结束后 `conda clean`，不留冗余层。

## 作业侧配合

[submit_xtalk_round1_job.sh](submit_xtalk_round1_job.md) 默认使用本镜像并传 `CONDA_SH=/opt/conda/etc/profile.d/conda.sh`，节点作业脚本以此激活镜像内环境；共享存储上的同名环境仍可用于本地开发，两者 freeze 记录分别归档。
