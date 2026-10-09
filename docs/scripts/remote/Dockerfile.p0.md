# `scripts/remote/Dockerfile.p0`

## 作用

构建 P0 集群镜像，供 `vc submit` 使用。镜像标签按集群约定递增：

```text
docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2
```

## 基础镜像与内容

- `FROM docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk:v0.17`：已含 CUDA 12.8.1、`/opt/conda`（Python 3.11）、torch 2.9.1+cu128、vllm；
- `PIP_INDEX_URL` 覆盖为清华源加速构建；
- `PYTHONNOUSERSITE=True` 避免 `~/.local` 用户包穿透文件系统挂载污染环境；
- 安装 `sudo`、`ffmpeg`（音频服务所需，超算容器以普通用户启动）；
- 用 `environment.yml` + `requirements.txt` 在 `/opt/conda/envs/interclarify-dev` 建立固定的 Python 3.10 环境；pip 保持 `environment.yml` 固定的 24.0，**不执行 `pip install --upgrade pip`**，避免版本漂移；
- 复制仓库快照到 `/opt/interclarify`，运行期再挂载 `/hpc_stor03` 读取模型与写产物；不执行递归 `chmod`（默认权限已可读，递归 `chmod` 在本机 overlay2 会触发 `max depth exceeded`）。

## 构建与推送

```bash
# 本机 overlay2 对旧式构建器会报 "max depth exceeded"，请使用 BuildKit：
DOCKER_BUILDKIT=1 docker build -f scripts/remote/Dockerfile.p0 \
  -t docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2 .
docker push docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-interclarify-p0:v0.2
```

registry 不允许覆盖已有 tag，升级需递增版本号。模型权重与数据集不进镜像。
