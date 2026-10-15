# X2 独立环境准备

`setup_x2_asr_env.sh` 固定官方源码提交和权重 revision，稀疏下载推理代码，创建独立 conda 环境，按官方 requirements 安装 Transformers 后端及 HTTP 服务依赖，下载模型并保存 pip freeze。默认使用可访问的 HF 镜像；`X2_HF_ENDPOINT` 可覆盖。只在远端运行，不修改既有 ASR/TTS 环境。
