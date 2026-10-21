# Nemotron 服务契约测试

`FakeEngine` 按真实可读窗口输出；`NemotronServiceTests` 检查独立读取、暂停、单流所有权、取消后新 UUID、EOF 尾部和积压上限，以及回写拒绝。使用 FastAPI TestClient 与后台 worker，不加载模型。运行 `conda run -n interclarify-dev python -m unittest discover -s tests -p test_nemotron_asr_service.py -v`；不替代远端模型验收。

`test_float_wav_keeps_speech_amplitude` 写入实际IEEE float WAV并核对转换后的非零PCM样本，防止有声输入被错误舍入成零。
