# 句读与停顿审计检查

`tests/test_layer1_surface_audit.py`用`unittest`检查审计结论易混淆的边界，无模型依赖。`SurfaceAuditTests`确认候选只删除长轮末尾点号、内部句号/逗号保留、引号闭合和小数处理明确；检查字符边界分类；确认分层抽样不重复使用同一用户轮，缺失类别与未签署状态保留。

运行方式：`conda run --no-capture-output -n ml-hw1 python -m unittest discover -s tests -p test_layer1_surface_audit.py`。这些检查不验证真实ASR质量，也不代替远端全量数据审计。
