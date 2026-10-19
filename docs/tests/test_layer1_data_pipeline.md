# 数据管线测试

`tests/test_layer1_data_pipeline.py` 用 unittest 覆盖 004 代码，无远端模型或 GPU 依赖。`CharacterTokenizer` 是可逆字符替身，用于检查原文跨度、监督和控制逻辑；另用真实 tokenizers 库构建最小 tokenizer 测试单 token/EOS/BOS 核验，不冒充发布 tokenizer 的真实数据验收。

`DataPipelineTests` 覆盖五类控制、停顿/插话/附和/思考、插话丢弃旧回答尾部、单片段插话后独立 finish、无后续轮不伪造插话、固定种子重放与 epoch 差异、保护句读、三视图目标和分拍不变、user/header mask、每事件一次监督、无未来用户输入、超长事件拒收、T3 500/500、Jaccard 前缀召回、切分前去重、外部来源验真、构建/恢复及产物篡改拒收。

本地在 conda 环境运行：`conda run -n paratalker-dev python -m unittest discover -s tests -p test_layer1_data_pipeline.py -v`。完整来源生成、发布 tokenizer 和集群测试按远端任务单执行，不由替身测试结论代替。
