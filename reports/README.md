# 实验报告

当前路线为 **SoulX-Duplug 官方配置＋并行 X2Streaming-ASR**。第一阶段 ASR-Frontend 的验收报告位于 [docs/reports/soulx](../docs/reports/soulx)，本目录只保留报告索引与原始产物规则。

## 当前前端结果

| 报告 | 状态与用途 |
| --- | --- |
| [原生控制与独立 X2 交付](../docs/reports/soulx/20261102-native-independent-frontend/README.md) | NTF-015／016 本地实现与契约验收 |
| [联合提交交付](../docs/reports/soulx/20261102-ntf017-joint-publication/README.md) | NTF-017 文本／状态／进度联合写入 |
| [完整预热与三轴预检](../docs/reports/soulx/20261103-ntf018-warmup/README.md) | NTF-018 完整预热、真实权重对照、并发三轴 3/3 |
| [固定 FDB30 验收](../docs/reports/soulx/20261103-ntf019-fdb30/README.md) | NTF-019 独立正文与原生状态验收，用户审核通过 |
| [取消 800ms 停止条件](../docs/reports/soulx/20261103-latency-limit-removal/README.md) | NTF-030 延迟照实记录，容量与资源保护保持 |

## 原始产物规则

Git 只保留审阅后的 README 汇总：结论、关键分母、限制、源码／模型版本和原始产物位置。逐例 JSON／CSV、trace、样本正文、资源采样与完整 manifest 保存在远端 run 及本地 `artifacts/`，不推送到 GitHub，也不使用 `git add -f` 绕过此规则。

权重、音频、大日志和本地实验产物不提交 Git；Git 历史不重写。
