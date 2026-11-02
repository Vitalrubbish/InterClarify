# 清除comparison历史实验

`scripts/remote/reset_comparison_experiments.py`只用于用户明确要求的NTF-014维护，不执行GPU任务。`inspect()`限制目标为当前用户的`~/turncontrol-comparison`，逐项分类并检查旧实验Git源码是否有未提交修改；未知目录或脏源码立即停止。

未跟踪的`__pycache__/*.pyc`／`*.pyo`属于运行产物，可随实验删除，不当作未提交实现；其他文件仍严格检查。

保留`models`、`envs`、`scoring-models`、`environment`、`wheelhouse`、`upstream`及公共`cache`。删除对象仅为历史实验`campaigns`、`inspection`、`managers`、`repository`、`runs`、`scripts`、`source`、`submit_logs`、`tmp`和根目录bundle／tar传输包。删除不跟随目录符号链接，不扫描或复制模型、conda。

`main()`默认仅生成清单，`--execute`执行已授权清理，使用1CPU，串行处理，限定十分钟。输出必须位于清理根目录之外且不可覆盖；逐项保存计划、文件大小、完成状态、磁盘余量及失败原因。它没有类，依赖Python标准库，在远端既有conda中运行。操作前调用方必须确认无相关调度作业或后台管理器；本脚本不自动杀进程，不操作comparison之外的实验。

调用形式：`python reset_comparison_experiments.py --output /path/outside/comparison/plan.json`，随后指定独立输出文件并加`--execute`。运行后仅剩上述公共资产，旧comparison加载器与worktree不可再作为新实验依赖。
