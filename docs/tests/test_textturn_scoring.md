# TextTurn 机会评分测试

对应 `tests/test_textturn_scoring.py`，只检查三项容易虚增成绩的边界：提前误 start 后不能由正确锚点补救，缺失停顿预测不能算正确等待，及时性必须包含窗内480ms等待。使用少量合成记录，无模型、GPU或集群作业。

v2将缺失停顿预测断言为unknown且实际错误为0，不再断言误抢话率为100%；未知仍保留计划分母，不能据此算成功。

TT-010增加一项完整轨迹回归：listen前缀与smooth锚点原有不同opportunity_id时，前缀错误start不能被后续正确start抵消；旧格式三项检查保留。
