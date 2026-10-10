# `scripts/remote/build_round1_flash_attn.sh`

## 整体作用

**回退脚本**：在 round-one 镜像内编译出一个与运行栈完全匹配的 `flash-attn` wheel，放到 `$XTALK_ROUND1_ROOT/wheels/`，供镜像构建时以 `--find-links` 直接安装。

正常情况下 round-one 镜像**不需要编译 flash-attn**：MOSS 环境（torch 2.9.1+cu128）直接使用 wheelhouse 里的官方预编译 wheel（`flash_attn-2.8.3+cu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl`，见 [Dockerfile.round1.md](Dockerfile.round1.md)）。只有当目标组合没有官方/社区预编译 wheel 时，才用本脚本自行编译（脚本默认单架构 sm_80、`MAX_JOBS=8`、`NVCC_THREADS=1`，并用 `docker --memory/--cpus` 限制宿主占用）。

## 为何要限制资源

flash-attn 编译极其吃内存：每个 nvcc 作业峰值约 8–9 GB，且 `setup.py` 默认会为 `FLASH_ATTN_CUDA_ARCHS`（默认 `80;90;100;120`）**四个架构**编译，并用默认 `MAX_JOBS`。此前一次无上限的编译直接把共享调试机 `d6-hpc-debuggpu-001` OOM 崩溃。因此本脚本刻意保守，**默认不允许占满宿主**。

## 关键做法

- **单架构**：默认 `FLASH_ATTN_CUDA_ARCHS=80`。flash-attn **不读** `TORCH_CUDA_ARCH_LIST`（脚本曾误设 `8.9`），只读 `FLASH_ATTN_CUDA_ARCHS`。sm_80 的 cubin 可按小版本前向二进制兼容运行在 8.x 设备（如 RTX 4090 / sm_89），故单个 80 即可。
- **跳过下载探测**：`FLASH_ATTENTION_FORCE_BUILD=TRUE`，避免 `setup.py` 先去 GitHub 拉预编译 wheel 造成长时间无日志等待。
- **宿主级内存上限**：`docker run --memory --memory-swap --cpus`（默认 `48g`/`8`），即使用户态进程失控，也只会被 cgroup OOM，而不会拖垮共享机。
- **并发上限**：默认 `MAX_JOBS=8`、`NVCC_THREADS=1`，进一步压低峰值内存。
- **产物落盘**：编译完成的 `flash_attn-*.whl` 拷入 `$XTALK_ROUND1_ROOT/wheels/`，供后续镜像构建复用。

## 用法与可覆盖项

```bash
bash scripts/remote/build_round1_flash_attn.sh
```

可覆盖：`IMAGE`、`FLASH_ATTN_VERSION`、`FLASH_ATTN_CUDA_ARCHS`、`MOSS_ENV`、`MAX_JOBS`、`NVCC_THREADS`、`DOCKER_MEMORY`、`DOCKER_CPUS`。
