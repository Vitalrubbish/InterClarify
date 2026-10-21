# Issue 067：暂缓不可用judge并继续完整FDB时序评测

状态：进行中，2026-10-21。

r2已通过官方Parakeet语音与静音对齐预检，但现有端点未提供gpt-4-turbo/gpt-4o，调用返回503。用户明确选择暂缓GPT评分，之后再提供支持原judge的端点或模型；本轮不改用其他judge。

## 当前范围

以独立r3继续完整319例实时回放、官方词级转写和两轴时序指标。Smooth Turn-Taking运行官方evaluate.py；User Interruption按冻结官方代码相同的1秒/3词规则逐例计算TOR与响应延迟，保留原始负延迟与官方归零口径，零有效回复的延迟为缺失。回答相关性分数为null，judge_status=deferred_by_user，不调用API或编造评分。

新增显式defer-judge入口，任务默认遵循本次用户决定。评分summary区分requested_scope_passed与full_scoring_complete；本轮请求范围执行成功不代表GPT评分已完成。保留原对齐结果，未来judge可独立补跑。

- [ ] 更新脚本/文档及阈值、漏答、负延迟回归。
- [ ] 冻结新源码，保留r1/r2失败，提交r3并确认正式回放启动。

模型、数据、300/1200ms、KV、600ms拍长、显式生成策略及资源8小时/双4090不变。
