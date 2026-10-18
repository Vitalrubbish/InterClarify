# TTS 环境与权重准备

`scripts/remote/prepare_tts_selection.sh` 在远端准备 Pocket/Kokoro 共用的实验专属 conda 环境（两模型分别运行，避免重复复制 CUDA 依赖），保留可复用的 Kyutai conda 环境和权重，下载仅需文件及音色。只做依赖安装与缓存准备，不在登录节点运行模型。

无类。脚本等待 conda clone 完成后安装固定版本运行包；下载器通过官方 Hugging Face 元数据固定提交，保存 manifest，支持设置 `HF_ENDPOINT` 为可达镜像。凭据仅从远端已有文件读入进程，不能写入日志、manifest 或仓库。

共享盘克隆可能较慢，日志在独立实验目录，所有新文件与旧实验隔离。模型加载仅在调度的 GPU 作业进行。


Kokoro 的英文 G2P 需要 `en_core_web_sm==3.8.0`。服务器不能直连 GitHub Release 时，先在本地下载[官方 wheel](https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl)，上传到 `$ROOT/models/`，脚本按固定文件名安装。Pocket 3.3.0 的默认英文配置把权重和 tokenizer 固定到各自 revision，下载器从包内 YAML 读取这些引用，避免误拉全部语言权重。无克隆权重和预置 Alba 音色足以完成本次测试；不要求用户接受克隆权重门禁。

本轮该官方 spaCy wheel 的 SHA256 为 `1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85`。
