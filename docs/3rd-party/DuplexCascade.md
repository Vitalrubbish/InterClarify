# DuplexCascade 第三方源码

## 文件作用

`3rd-party/DuplexCascade` 保存官方 DuplexCascade 推理服务源码的仓库内快照。该目录由 Git 管理，供服务器通过项目 GitHub 仓库同步后直接复用；模型权重、基础模型和运行产物不放在此目录。

## 来源与版本

- 来源仓库：`https://github.com/sbintuitions/DuplexCascade`
- 固定提交：见 `3rd-party/DuplexCascade/SOURCE_COMMIT`
- 当前固定提交：`42893024ca90c8de8ac3ed624467ebc123512ff8`
- 许可证：见 `3rd-party/DuplexCascade/LICENSE`

## 使用约束

`scripts/remote/prepare_p1_assets.py` 默认校验 `SOURCE_COMMIT`，也允许服务器通过 `--source-root` 或 `INTERCLARIFY_DUPLEXCASCADE_SOURCE` 使用独立 Git checkout。修改官方源码时必须同步更新来源提交、许可证记录和复现实验文档；不得把 `model_state.safetensors` 等大文件加入仓库。
