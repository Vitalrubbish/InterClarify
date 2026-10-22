# X2-Turn 固定上游源码准备

`scripts/remote/prepare_x2_turn_sources.sh` 在**登录节点**物化部署需要的两个固定源码检出。调度节点无法访问 `github.com`（`pdcpu` 作业里 TLS 连接被中断），因此这一步不能放进 `vc` 作业；脚本只做浅克隆与哈希记录，不安装、不推理。

## 固定内容

- X2-Turn `67ec3fe49f1977ee3129f7eaed603c04d8ed23c5`，完整浅克隆，提供 overlay 补丁、导出工具与状态头辅助模块。
- vLLM `v0.19.1`（`b1388b1fbf5aaef47937fabe98931211684666a6`），使用 `--filter=blob:none --no-checkout --depth 1` 的偏克隆，再用非 cone 模式稀疏检出补丁涉及的 10 个文件。只传这 10 个文件对应的 blob，避免在慢速链路上下载整个仓库。

稀疏检出后工作区是干净的：被排除的文件不在磁盘上，`git status --porcelain` 为空，因此作者安装脚本的"commit/tag/干净工作区/补丁可应用"检查仍然有效。

## 使用

```bash
X2_TURN_ROOT=~/interclarify-x2-turn-complete \
  bash scripts/remote/prepare_x2_turn_sources.sh
```

远端 GitHub 实测速度较低（约 60–70 KB/s），脚本可以放在 `nohup` 下运行并轮询日志。若检出已存在且提交一致，脚本直接复用；vLLM 目录不完整时先删除再重建。

## 输出

`ROOT/env/x2_turn_source_lock.json` 记录两个仓库路径与提交、vLLM 克隆方式、稀疏文件清单及各自 SHA256、补丁文件 SHA256。安装阶段会重新核对提交与标签，缺失或缺锁时直接失败，不在计算节点尝试联网克隆。
