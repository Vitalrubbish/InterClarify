# Nemotron＋SoulX适配契约检查

对应`tests/test_nemotron_soulx_frontend.py`。四个CPU场景检查词内字符追加不会插空格、两消费者一致、源回写／序号／generation／观察上界错误拒绝、EOF不改在线快照、token公共前缀以及同话轮来源锁定。使用真实发布和Context校验方法，不加载模型，不以测试替身声称五状态模型质量通过。

补充检查同一个原始字符前缀在控制器reset后不能被重新计作新内容，门控关闭时不消费，即使已有更长来源。

运行：`python -m unittest discover -s tests -p 'test_nemotron_soulx_frontend.py' -v`。真实音频、缓存重放与共享GPU行为由远端组合探针验证。
