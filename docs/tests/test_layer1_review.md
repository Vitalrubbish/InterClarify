# 人工审查材料与抽样测试

`tests/test_layer1_review.py`使用unittest，无真实权重。`ReviewTests`验证固定抽样不受遍历顺序影响、每类20条且split比例12/4/4、同类对话不重复、24条安排双人但签署全部为空、覆盖不足如实报告，以及审查材料绑定产物摘要、篡改拒收且不会修改数据目录的人审状态。

小型tokenizer替身只用于可读输出检查，不代替发布tokenizer数据审计。在conda运行：`python -m unittest discover -s tests -p test_layer1_review.py -v`。真实导出由远端正式数据作业执行。
