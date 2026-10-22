# X2-Turn FLEURS 评测记录

更新：2026-10-22。固定输入、部署、真实时钟回放与两类独立评分均已完成；正式结果见 [X2Q-014 报告](../x2_turn_fleurs_evaluation.md)。

| 阶段 | 证据 | 状态 |
| --- | --- | --- |
| X2Q-009 固定 100 test + 1 dev | [20261022 FLEURS 子集](20261022-fleurs-subset/README.md) | 已完成恢复与独立复核；不宣称与旧 manifest 逐文件验同 |
| X2Q-010 冻结版本服务 | [20261022 部署](20261022-deploy/README.md) | 已完成 vLLM 0.19.1 + overlay、480 ms delay 与 dev 协议诊断 |
| X2Q-014 正式测试 | [X2Q-014 报告](../x2_turn_fleurs_evaluation.md) | 100 条真实模型回放；WER 22.53%、complete 1.0%；逐例结果与远端路径见报告 |

原始 WAV、manifest、下载事件、模型、环境锁与正式 trace 保存在远端 `~/interclarify-x2-turn-complete`；Git 只收简明报告和脚本。X2Q-010—014 的部署、回放与评分结果不覆盖既有记录。
