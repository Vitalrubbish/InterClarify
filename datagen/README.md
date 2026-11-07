# 对话数据试造

五个原创场景、13 条派生轨迹，以及 SoulX-Duplug、Layer 1、Layer 2 三类 SFT 语义视图。先看[逐场景中文审阅稿](pilot/review.md)，再读[实现与覆盖说明](../docs/datagen/README.md)。

场景源为 `scenarios.json`，导出器为 `build_pilot.py`。使用现有 conda 环境运行；输出目录必须不存在：

```bash
bash datagen/run_remote_pilot.sh /path/to/conda-env /path/to/new-output
```

当前是文本与模拟时序样例；音频、真实前端回放及独立审核待补，所有样本关闭正式训练资格。
