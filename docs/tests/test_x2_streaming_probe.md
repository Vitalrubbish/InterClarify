# X2 探针本地测试

`tests/test_x2_streaming_probe.py`在本地conda运行，无需加载模型。`ProbeTests`覆盖未闭合组拒绝提交、PAD／WORD不冒充EOS、历史token不变及回改证据、多文本token共用同一音频帧、解码上限不伪造EOS、实际观察与EOF补零分离，以及四条门槛的完整性和边界值。

执行：`conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -p test_x2_streaming_probe.py -v`。模型形状、显存和真实节拍验证必须通过远端调度作业完成，本地通过不等于NTF-011通过。
