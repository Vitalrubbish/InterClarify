# 来源下载恢复测试

`tests/test_fetch_layer1_sources.py` 使用 unittest 和模拟 HTTP response，不发网络请求。`Response` 模拟正常块、断流和Range响应；`SourceRecoveryTests` 检查断流后正确续传、服务器忽略Range时重下、错误Content-Range拒收、最终摘要错误拒收、有界超时重试及已有文件重新验真。

在本地 conda 环境执行：`conda run -n paratalker-dev python -m unittest discover -s tests -p test_fetch_layer1_sources.py -v`。测试证明下载恢复行为，不替代远端全部实际shard验真。
