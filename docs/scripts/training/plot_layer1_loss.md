# 训练loss曲线导出

`scripts/training/plot_layer1_loss.py`读取080已核对的`loss_analysis.json`，用matplotlib生成独立PNG/SVG。无业务类；`plot`按每50步真实token/权重分母聚合绘制普通CE、加权CE及正文加EOS剩余类别，另画五类控制目标NLL的对数曲线，warmup边界单独标记。

横轴为统计区间中点，末区间不足50步按实际记录；图形不插值成逐步数据，不绘制不存在的验证集曲线。英文图例避免字体依赖，中文解释在同目录报告。
