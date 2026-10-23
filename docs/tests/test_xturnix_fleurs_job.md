# XTurnix 受限作业入口测试

`tests/test_xturnix_fleurs_job.py` 只验证远端作业入口的本地合同，不提交集群作业、不加载模型、不读取远端数据。

- 两个 shell 入口文件存在、可执行且通过 `bash -n` 语法检查。
- 未知模式、缺少 `run_id`、包含路径跳转的 `run_id` 都在访问任何文件之前以退出码 2 拒绝。
- 调度包装会破坏含字面量 `JOB` 的变量名，因此提交命令使用 `XTURNIX_MODE` / `XTURNIX_RUN_ID`；旧名仅在不经过包装的直接执行中保留。
- 测试把 `HOME` 与 `XTURNIX_ROOT` 指向不存在的临时路径，从而确认参数校验发生在预检和目录创建之前。

运行：

```bash
conda run -n parathink-dev python -m unittest tests.test_xturnix_fleurs_job -v
```

作业真正启动服务、回放和评分的行为只能在远端调度 GPU 中验证；本测试通过不代表冒烟或正式回放成功。
