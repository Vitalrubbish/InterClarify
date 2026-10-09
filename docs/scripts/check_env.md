# `scripts/check_env.py`

## 作用

P0 环境验收脚本：确认当前解释器能导入核心依赖、打印版本，并在需要时确认 PyTorch 能看到预期 GPU。对应 [engineering_implementation.md](../engineering_implementation.md) 第 4.3 节验收门槛。

## 输入

- `--out PATH`：写人类可读报告（供日志/归档）；
- `--json-out PATH`：写机器可读 JSON 报告；
- `--require-gpu`：PyTorch 不可见 CUDA 设备时计入失败。

## 输出与退出码

- 检查 `CORE_MODULES`（torch、numpy、scipy、soundfile、librosa、websockets、PyYAML、fastapi、uvicorn、aiohttp、requests）；
- 记录可选模块 `sounddevice`（缺失只提示，不失败）；
- 采集 GPU 名称、算力（sm_89 应为 RTX 4090）与显存；
- 退出码 = 缺失核心模块数 +（`--require-gpu` 且无 CUDA 时 +1）；`status` 为 `PASS`/`FAIL`。

## 依赖

只依赖标准库与目标环境本身，避免“检查脚本自己装不上”的问题。X-Talk 和模型专属 extras 在 P1.0 固定后另行加入检查；不再沿用已删除的 DuplexCascade 专属依赖集合。
