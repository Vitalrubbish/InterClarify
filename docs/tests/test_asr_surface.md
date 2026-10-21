# 延后句读回归

`tests/test_asr_surface.py`使用`AsrSurfaceTests`核验句末无后续时不补点、停顿不刷新暂存、同拍和跨拍续说、跨用户轮/附和释放、对话重置与EOF残留。因果共享前缀检查确保未来是否续说不改变此前视图；篡改映射/提前补点须被审计拒绝。真实规划器对照检查原事件及目标不变，编码器用户mask和每事件单次监督保持。

在conda中运行`python -m unittest discover -s tests -p test_asr_surface.py`，不加载模型，不声称验证真实ASR毫秒级时序。

远端首轮触发的待发格式片段增加回归：没有字母/数字的源拍可在ASR视图暂时为no-voice，字符在后续释放后仍完整守恒，不错误套用旧T2删空门禁。
