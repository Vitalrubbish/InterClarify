# 原生加载器冻结检查

对应测试：`tests/test_native_soulx_loader.py`。`LoaderTests`核对当前官方子模块与冻结的21份源码、英文配置及资产清单；检查错误提交、脏工作区、缺失权重、资产摘要变化均被拒绝。

无有效本地资产时，加载器必须在导入模型模块／GPU分配之前失败。测试只创建临时小文件，不修改子模块或下载模型，不调用真实加载；真实依赖及权重兼容性留给远端验证。

NTF-052新增轻量加载集成检查：模拟FunASR若未指定ncpu就回到4线程的行为，运行加载器的实际资源配置与工厂替换，确认传入ncpu=2、加载后预算仍为2且execution.json与返回记录一致。依赖与模型均为替身，不加载真实权重。

运行：`conda run -n interclarify-dev python -m unittest discover -s tests -p test_native_soulx_loader.py -v`。
