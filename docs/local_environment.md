# 本地 conda 环境

本地统一使用 `interclarify-dev`，Python 3.10，依赖由 `environment.yml` 与 `requirements.txt` 固定。`environment.lock.yml` 记录当前已验证的完整包版本，用于快速复现。

## 创建

```bash
cd /path/to/InterClarify
bash scripts/remote/setup_env.sh
```

脚本默认使用清华 PyPI 镜像，不在环境已存在时自动升级；需要重建时：

```bash
IC_RECREATE=1 bash scripts/remote/setup_env.sh
```

## 从锁文件复现

```bash
conda env create -f environment.lock.yml
```

锁文件由当前环境导出，包含 conda 与 pip 的精确版本；日常开发仍以 `environment.yml` + `requirements.txt` 为准，修改依赖后重新导出：

```bash
conda env export -n interclarify-dev --no-builds | grep -v '^prefix:' > environment.lock.yml
```

## 验收

```bash
conda run --no-capture-output -n interclarify-dev python scripts/check_env.py
conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -v
```

`check_env.py` 应输出 `status: PASS`，核心模块缺失数为 0。本地 WSL 环境当前可见 RTX 5070 Laptop GPU（sm_120，约 8GB）；真实模型推理仍在远端 GPU 作业执行。

## 测试依赖

FastAPI `TestClient` 需要 `httpx==0.27.2`；更高版本与当前 Starlette 0.38 的 TestClient 接口不兼容。该依赖已写入 `requirements.txt`，不随开发工具升级。
