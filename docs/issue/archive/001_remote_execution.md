# Issue 001：官方 Word 输入远端验收任务单

状态：完成，2026-10-19。五例官方 Word 自由回放及集成生命周期检查通过，已归档。结果见 [验收报告](../../../reports/layer1_training/issue001-word-20261019/README.md)。

## 冻结资源与输入

远端根目录 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-issue001-word-20261019/`。通过 Windows SSH 配置的 guizhou 路由登录；真实权重仅通过 vc 单卡作业执行。两阶段均为 1×4090、8 CPU、32GB 主存，分别限时 1,200 秒，未超 4 GPU 小时诊断上限。

历史五例只有 token/累计文本，不能作为原生 Word；已使用冻结 Rust 服务补采，配置/二进制、音频及原始捕获 SHA256 见 word_manifest。已有产品环境和历史结果未覆盖。

## 执行与复跑

1. 源码复制到独立目录并保存逐文件 source.sha256。采集服务为既有 `moshi-server 0.6.4`，使用冻结本地 STT 配置、独立端口 31627，公开认证头 public_token；先用 dev 预热，再采集五例。准确启动脚本及环境路径保存于报告的 `word-capture-r2-job.sh`。
2. 采集客户端通过独立 conda `interclarify-dev` 实时发送 24kHz、80ms 音频，尾部有限静音排空，保存原始 Word 与到达时间。采集作业 `job-179234084264647775229-xuan-zhang` 退出 0。
3. 核对五例输入和摘要后关闭采集服务，单独调度模型对照；双方独立历史自由回放，首 Word 起拍、600ms、BF16、64-token 贪心，原样句读，不发送 EOF 让轮信号。

复跑对照时先冻结新的源码目录并使用新的输出路径，在 vc 单卡作业中运行：

```bash
LAYER1_COMPARISON_ROOT=/path/to/frozen-source \
LAYER1_COMPARISON_OUTPUT=/path/to/new-comparison \
LAYER1_WORD_MANIFEST=/path/to/verified-word_manifest.json \
  bash scripts/remote/run_layer1_runtime_comparison.sh
```

只替换上述实际路径，不展开 raw/完整词、时钟或句读组合；单步/固定输出仅在出现具体差异时排错。每个输出目录必须新建，失败保留。

## 完成结果

- [x] 词事件 11/11/14/16/16，最大音频投送迟到约 2.14ms，输入和原始捕获摘要已核对。
- [x] 五例共 136 拍，两路分别 28/26/26/28/28，请求、prompt/生成 IDs、历史、控制和正文一致。
- [x] 对照作业 `job-179234101532068397696-xuan-zhang` 退出 0；远端客户端 conda 的 7 项测试通过，含在途取消和新会话隔离。
- [x] 源码、模型、许可、时间线、退出码和汇总放行清单已保存；首轮 HTTP401/退出 1 原样保留。

原始消息、模型日志和采集完整发送计划留远端，仓库保留 Word 清单及完整逐拍 IDs 的紧凑副本。结果只放行 001，004/005 和 007 开训前准备仍未完成，训练保持关闭；真实产品音频与 FDB 仍由 008 验收。
