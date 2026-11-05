# FDB30 半双工消费检查

`tests/test_fdb30_half_duplex.py` 使用假回答会话测试联合状态消费者。覆盖 complete 启动、nonidle 取消、恢复后只追加新正文、重复 complete 无新字不启动、无效状态及空正文不启动、重复快照被拒绝。验证因果动作合同；真实生成、取消与录音在远端冒烟作业检验。
