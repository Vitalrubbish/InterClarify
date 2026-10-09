# `scripts/remote/build_xtalk_lean_base.sh`

## 整体作用

把 `xtalk:v0.17` 压平并剔除首轮用不到的内容，得到更小的基座镜像 `xtalk-lean:v0.1`，供 round-one 镜像 `FROM`。`xtalk:v0.17` 是 431 层的迭代链，后续层覆盖了早先安装的文件（最典型是 2.59 GB 的 `vllm==0.10.2` 层后来被 `vllm==0.16.0` 覆盖），这些死字节仍随镜像分发；同时它带着本组合不用的栈（paraformer/onnxruntime、IndexTTS/pynini、gradio/wandb/kubernetes/verl、node）。

## 核心步骤

1. `flatten`：用 `docker export | docker import` 把 `xtalk:v0.17` 压成单层，并通过 `--change` 回填 PATH、CUDA、`LD_LIBRARY_PATH`、`PYTHONNOUSERSITE` 等关键 env（约 32 GB → 25 GB，431 层 → 1 层）。
2. 构建一个只做删除的层：`strip_base.sh` 删掉 onnxruntime/funasr/modelscope/sherpa、pynini/pyopenjtalk、gradio/wandb/kubernetes/tensorboard/verl/pytriton、xformers、cupy、node 与 `/opt/xtalk`；**保留** vLLM 硬依赖（ray、numba/llvmlite、opencv、pyarrow、triton）与 torch/nvidia/transformers。
3. 再次 `flatten` 回收被删字节，得到 `xtalk-lean:v0.1`（约 22 GB，单层）。

## 约束

- 删除必须在 **build** 阶段进行（build 以 root 运行，才能删 root 拥有的文件）；集群里 `docker run` 会以映射用户启动，无法删除 `/opt/conda` 下的文件。
- 压平会丢失镜像的 ENTRYPOINT/CMD 与历史，脚本只回填运行所需 env；作业脚本自行指定命令。
- 不涉及模型权重；`PUSH=1` 时推送基座镜像。首轮验收镜像 `Dockerfile.round1` 已改为 `FROM ...xtalk-lean:v0.1`。
