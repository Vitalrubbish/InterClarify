# setup_asr_selection_envs.sh

从远端已有、版本固定的 X2 Python 3.12 conda 环境克隆三个隔离环境，复用包缓存，避免重复下载 PyTorch。不会修改源环境。无类。

为两个 Nemotron 环境核对 Transformers streaming RNNT 接口；Kyutai 另安装固定 Moshi 及必要依赖。每个环境写出 pip freeze。实际推理环境版本与来源均留档，环境构建失败时不提交 GPU 作业。
