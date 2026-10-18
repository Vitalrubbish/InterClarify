# Issue 001：官方 Word 输入对照验收

2026-10-19，结论：**001/001b 在声明范围内通过**。产品仍为 Nemotron EN160 + Kokoro，本报告不声明产品迁移、真实播放、训练恢复或 FDB 已通过。

## 运行与结果

远端根目录 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-issue001-word-20261019/`，单卡 RTX4090、8 CPU、32GB 主存。采集作业 `job-179234084264647775229-xuan-zhang`，对照作业 `job-179234101532068397696-xuan-zhang`，退出码均 0。

| 样本 | 原生 Word 数 | 参考/集成请求数 | 首次差异 |
| --- | --- | --- | --- |
| historical-1 | 11 | 28/28 | 无 |
| historical-2 | 11 | 26/26 | 无 |
| historical-3 | 14 | 26/26 | 无 |
| historical-4 | 16 | 28/28 | 无 |
| historical-5 | 16 | 28/28 | 无 |

合计 136 拍，prompt IDs、原始生成 IDs、提交历史、控制动作、停播意图和正文均一致。双方独立生成历史，没有强制另一侧输出。完整请求耗时参考约 0.066–0.350 秒、集成约 0.067–0.519 秒；这是本轮测量，不承诺任意 64-token 输出都满足 600ms。模型加载 55.16 秒，GPU 型号见 gpu.csv；本轮未另测峰值 RSS/显存，不将申请资源当作峰值。

历史 Kyutai token/累计文本记录未保存原生 Word，所以使用既有 Rust `moshi-server 0.6.4` 补采相同五例。采集前音频 SHA256 与旧 manifest 一致，先用 dev 预热；只把原始 Word 消息和实际到达时间交给比较器。24kHz、80ms 投送，补 2 秒静音排空，再等待 2 秒；最大投送迟到约 2.14ms。没有从完整转写倒推词边界，没有将 EOF 或人工让轮信号交给 LLM。

参考固定官方提交 `42893024ca90c8de8ac3ed624467ebc123512ff8`，逐 Word strip、每拍空格连接、首非空 Word 后 600ms 起拍；发布 checkpoint/tokenizer、BF16、64-token 贪心。比较器直接使用原版 AST 控制循环，集成侧使用既有 Assembler/RuntimeAdapter。仅一套配置，不再运行 raw/完整词/句读交叉矩阵。

## 生命周期与失败

远端客户端 conda 执行 7 项测试全部通过，见 `word-comparison-tests.log`。在途关闭取消真实总线中的阻塞模型流；未完成 assistant IDs 不提交，关闭后不再追加正文；新会话从空历史开始，不混入旧问题或部分回答。该测试替换了模型推理，不声称测过 GPU 计算释放或实际扬声器停止，后者由 003/008 验收。已产生的旧音频事实不撤销。

首轮采集 `job-179234074671283321969-xuan-zhang` 因缺少冻结服务要求的公开认证头返回 HTTP401，退出 1；失败日志保留。修复客户端请求头后新作业成功，没有改服务授权或覆盖失败。旧 raw/有界 complete_word 报告仍为诊断，不改写成官方 Word 证据。

## 资产与许可冻结

实际模型、tokenizer、embedding/head 和已有 q/v LoRA 摘要引用 `../issue001-inventory-20261018/inventory_summary.json`；完整恢复由本轮模型 health 和已有 strict 加载证据确认，训练加载与零更新数值对齐仍归 005。本轮没有重新哈希全部大权重。源码实际字节见 `source.sha256`；采集与首轮失败版本相对本轮源码的差异见 `source_revisions.json`，完整原件保留远端；采集成功后仅更新测试文件。`source_versions.txt` 记录基线提交，未来提交不会改写 run 来源。

`asset_review.json` 冻结远端许可/模型卡路径和 SHA256，完整原文保留远端 `license_sources.json`。本次核对范围是当前研究推理与有限继续训练准备，未执行权重再分发：

| 资产 | 冻结许可来源与执行边界 |
| --- | --- |
| DuplexCascade 源码/发布权重 | MIT；保留原版权和许可；基础 Qwen2 的条款仍须保留 |
| Qwen2-7B-Instruct | Apache-2.0；保留许可、通知和修改记录 |
| Nemotron EN | 模型卡指向 [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/)；已核对 2025-10-24 版及其引用的 [Trustworthy AI 条款](https://www.nvidia.com/en-us/agreements/trustworthy-ai/terms/)，后续分发须带协议和归属通知，不将其称为 Apache/MIT |
| Kokoro/af_heart | [固定 revision 模型卡](https://huggingface.co/hexgrad/Kokoro-82M/blob/f3ff3571791e39611d31c381e3a41a3af07b4987/README.md)声明 Apache-2.0；snapshot 缺单独 LICENSE，不伪造已下载副本，分发前须随附许可并保留原归属 |
| Kyutai 参考 STT/服务 | 权重卡声明 CC-BY-4.0，代码 MIT/Apache-2.0；保留 Kyutai 来源、许可链接及本地配置修改说明，参考权重不改作训练材料 |
| UltraChat | 已冻结来源清单声明 MIT；正文未下载验真，004 继续承担实际数据文件和切分审计 |

许可来源与当前使用边界已登记；未来分发与新的使用场景仍须沿用对应许可，不把本次核对扩展成无限制授权。

## 证据与后续

`data/word-capture-r2/word_manifest.json` 保存词事件和每例原始捕获摘要，原始消息/发送计划留远端。manifest 原件 SHA256 为 `e8ae3fdb21f7a1d453fa42d3be4824d58e623629187be0b1983500c9790aba0e`。`data/word-comparison-r1/comparison/` 保存全部逐例 IDs、时间线和汇总；JSON 仅压缩空白，字段值不变，原件及紧凑副本字节摘要分别记录。

放行仅指 001 的官方输入与控制执行检查。004 数据审计、005 训练恢复/零更新及资源短跑、007 规则和样本准备尚未完成，`training_released` 保持 false。003 用户已反馈句内分段不连续，待 003d 修复及 003c 复听；本轮没有启动训练或修改 TTS 策略。
