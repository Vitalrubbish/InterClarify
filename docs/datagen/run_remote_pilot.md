# `datagen/run_remote_pilot.sh`

整体功能：在本地或远端既有 conda prefix 中，以相同资源限制调用文本试造导出器。不加载 GPU 模型，不安装或修改环境，不涉及 NTF-054。

脚本无类。两个位置参数为 conda prefix 和新的输出目录；入口检查 `conda-meta/history` 和目录不存在。固定计算线程为一，将进程绑定到当前允许 CPU 集合中的一个 CPU，限制地址空间 2 GiB、单文件 32 MiB、CPU 时间 110 秒、墙钟时间 120 秒；超时后最多再等 5 秒。导出器内部限制总产物 16 MiB。

```bash
bash datagen/run_remote_pilot.sh "$CONDA_PREFIX" /path/to/new-output
```

调用方需串行执行，只启动一个工作进程，并保存标准输出及退出码。模型回放与集群推理需要单独的调度任务，本脚本不能作为这些任务已完成的证据。
