# 原生模型离线加载

对应实现：`scripts/runtime/native_soulx_loader.py`。本文件没有新增模型类，直接构造官方`service.model.TurnModel`，再交给`NativeSoulX`。不导入comparison加载器，不下载或复制权重。

`verify_source()`核对官方Git提交、干净工作区和21份Python文件摘要。`verify_files()`逐文件流式计算摘要，错误或缺失立即失败。冻结内容见[配置说明](../../configs/native_soulx.md)。

`load_native_controller(upstream, soulx_assets, sensevoice_assets, run_dir, **callbacks)`先完成所有源码、SoulX及SenseVoice资产校验，再在独立结果目录以排他创建方式保存实际配置与`native_assets.json`。只将官方配置中的三个模型路径解析为已有本地资产路径，保留官方初始化、种子和reset顺序。

加载期间串行保护官方通用模块名，发现其他路径的`service/model/config/utils`缓存即要求新worker。临时将官方SenseVoice构造中的远端模型名解析为经过校验的本地目录，保持其余参数和原生后处理；离开加载作用域即恢复FunASR工厂和离线环境变量。状态词表校验与设备同步完成后才返回封装。

必须在已有conda环境的新模型worker中使用；真实加载及GPU推理只由NTF-018／019远端作业调用。当前本地检查只验证源码、资产错误提前退出与摘要拒绝逻辑，没有加载真实模型。
