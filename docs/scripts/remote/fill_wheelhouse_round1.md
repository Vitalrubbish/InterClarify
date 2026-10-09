# `scripts/remote/fill_wheelhouse_round1.sh`

## 整体作用

预填首轮 wheelhouse 缓存。首轮镜像构建以 `wheels/` 为 `--find-links` 本地缓存，其余依赖从 pypi.org 拉取，因此本脚本是可选的；在准备节点上先把大 wheel（torch cu128、vllm、transformers）缓存下来，可以让后续构建更快、更少受外网波动影响。

## 核心流程

- 以 `xtalk-round1-tools` 环境的 Python 作为下载器（`ROUND1_FILL_PYTHON` 可覆盖）。
- 各环境独立 `pip download` 到 `wheels-staging/<env>/`：tools、vllm、asr（transformers 4.57.6 闭包）、moss（torch/torchaudio 2.9.1+cu128、transformers 5.0.0）、client（直接解析本地 `xtalk[example,dev]` 项目）。
- 独立解析避免 Qwen 栈（transformers 4.57.6）与 MOSS 栈（transformers 5.0.0）的版本冲突；默认索引为 `pypi.org`（阿里云镜像对个别 wheel 会卡死），额外索引为 PyTorch cu128 官方源。
- 全部结束后把所有 staging 目录下的 `*.whl` 复制进 `wheels/`，同名覆盖；打印最终 wheel 数量。

单个环境下载失败只告警不中止，便于在部分镜像不可达时仍尽量补齐；脚本不修改源码树与镜像。
