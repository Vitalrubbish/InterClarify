# X2-Turn 固定源码包构建与离线交付

`scripts/remote/build_x2_turn_source_bundle.py` 在**有 GitHub 访问能力的机器**上构建一个很小的源码包，供无法访问 GitHub 的调度节点使用。它只取固定版本需要的文件，不下载仓库历史，也不下载无关文件。

## 背景

远端实测：调度节点访问 `github.com` 直接失败，登录节点 git 数据通道约 1.5 KB/s 且连接不稳定。vLLM 完整源码树无法在合理时间内取得，也没有 scp/sftp 通道。因此把部署真正需要的文件打包后经登录节点 PTY 传入远端。

## 包内容

- `vllm/` 下补丁涉及的 10 个文件的**打补丁前**内容，取自固定提交 `b1388b1fbf5aaef47937fabe98931211684666a6`（标签 `v0.19.1`）。
- `x2/voxtral-realtime/patches/vllm-voxtral-mtp.patch`：作者 overlay 补丁，取自 X2-Turn `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5`。
- `x2/voxtral-realtime/integrations/vllm/.../voxtral_mtp_utils.py`：状态头辅助模块。
- `x2/voxtral-realtime/integrations/vllm/tools/export_mtp_for_vllm.py`：权重导出工具。
- `manifest.json`：两个提交、每个文件的 git blob SHA-1 与 SHA256、补丁摘要。

## 校验方式

- 构建时用 `git hash-object` 核对 10 个文件与补丁 `index <pre>..` 前置哈希一致，不一致直接失败；X2-Turn 文件同时核对工作区与 `HEAD:path` 的 blob 一致。
- 安装阶段再次核对：wheel 中每个文件的 blob 必须等于补丁前置哈希，包内文件同样；随后在临时 git 索引里执行 `git apply --index`，由 git 校验前置哈希并核对应用后的 `index ..<post>` 后置哈希。这一步等价于"文件内容与固定提交逐字节相同"，且不依赖网络。

## 本地构建

```bash
python scripts/remote/build_x2_turn_source_bundle.py \
  --vllm-checkout /path/to/vllm-at-v0.19.1 \
  --x2-turn-checkout /path/to/X2-Turn-at-67ec3fe \
  --output /tmp/x2_bundle
```

vLLM 检出可先做 blob 过滤的稀疏检出，只保留这 10 个文件；X2-Turn 用一次浅克隆即可。输出 `x2_turn_sources.tar.gz`（约 100 KB）与 `x2_turn_sources.manifest.json`。

## 传送到远端

远端没有 scp/sftp。用交互 PTY 传入远端 `ROOT/source/`：

1. `base64 -w0 x2_turn_sources.tar.gz` 后在远端 `base64 -d` 还原，逐字节分段写入，避免单行过长。
2. 同时传入 manifest。
3. 用 `sha256sum` 核对压缩包摘要，并把该摘要作为 `X2_TURN_SOURCE_BUNDLE_SHA256` 传给安装作业；摘要不一致时安装阶段直接失败。

包只包含公开模型代码与补丁，不包含权重、音频或凭据。压缩包与解压目录都计入整轮资产预算。
