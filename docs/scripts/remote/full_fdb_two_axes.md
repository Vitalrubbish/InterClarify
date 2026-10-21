# full_fdb_two_axes.py

## 功能与边界

完成 FDB v1.0 两轴的输入冻结、暂存、真实音频回放调度与官方评分；不新增产品模型或播放通路。`AXES` 将 119 例 `candor_turn_taking` 映射到 `smooth_turn_taking`，200 例 `synthetic_user_interruption` 映射到 `user_interruption`。

## 核心方法

- `freeze`：验证两轴完整数量、输入时长与标注，计算 `input.wav` 和必要标注的 SHA256，生成远端独立 manifest。
- `stage`：先完整核对源文件，再复制到新目录；排除旧 `output/rating`，不覆盖既有目录。
- `infer`：调用 `duplex_a4_replay.run_fdb_batch`，逐轴复用当前 ASR/LLM/TTS 链路；检查全部例数，保留漏答、与原音频等长的官方输出及独立诊断尾窗。
- `preflight_judge`：只验证 judge 端点与模型可用性，不打印凭据。
- `score`：复用 `run_fdb_llm_judge` 的工作副本、密钥读取和指标解析，用评分 conda 直接运行官方 `asr.py` 与 `evaluate.py`。Smooth 轴不需要 API；`--defer-judge` 跳过 User Interruption 的 API 判题。

## 评分口径

`timing_metrics` 按冻结官方脚本的相同 TOR 规则逐例统计：无词或总词跨度不足 1 秒且词数不超过 3 判为未接话；接话延迟按官方口径将负值归零，同时保存原始负值，零接话时延迟为 null。

输出分别标注“请求范围执行通过”和“完整评分是否完成”，GPT 未执行时明确为 pending。原始音频与大 trace 留远端。
