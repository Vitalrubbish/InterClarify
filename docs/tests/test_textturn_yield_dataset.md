# 让轮与播放生命周期边界测试

`tests/test_textturn_yield_dataset.py`通过小型内存tokenizer检查构造合同，不依赖模型或测试来源。

`YieldDatasetTests`覆盖五组必要边界：无停止词的首个可判定更新stop及确认延迟；附和转接管、unknown全屏蔽及未来文本隔离；重复／旧版本／旧轮和非追加修订；生成完成后的Speak、播放finish、一次消费和持久终态；首次正文前stop、同刻两种顺序、多输出、异常及截断。构造器闭环校验和测试检查均为数据合同证据，不是模型质量结果。

本地已有conda运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_textturn_yield_dataset.py -v`。无需新GPU作业。
