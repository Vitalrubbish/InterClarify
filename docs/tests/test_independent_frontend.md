# 同源输入与独立正文契约检查

对应测试：`tests/test_independent_frontend.py`。`FakeEngine`按真实`decode_emit`协议产生确定性WAIT或EOS闭合组，`Clock`提供可控单调时钟；不加载X2权重。集成检查搭配实际官方SoulX方法的CPU依赖模型。

`X2Tests`覆盖多个子词闭合成一词、多词组、WORD不发布、WAIT无新字仍推进、64 token超限与开放组保留、前缀改写拒绝、正文时间不被空步骤刷新，以及取消中的迟到回调。

`AudioTests`覆盖两种完成顺序、当前周期两路完成后才推进、第一帧结果先于第二帧及控制发布、生产者在推理期间继续入账、输入到达与模型启动时间区分、源PCM摘要／实际波形一致、startup采样偏移、reset后未读PCM及X2正文连续、EOF部分块、800ms／4MiB上限与分配前预算、单路失败、关闭／溢出期间取消、关闭等待短回调结束并拒绝其余发布、过期与重复回执、以及隐式输入转换拒绝。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_independent_frontend.py -v`。这些测试验收本地调度和发布合同，真实形状／延迟／词尾质量仍由NTF-018／019验证。
