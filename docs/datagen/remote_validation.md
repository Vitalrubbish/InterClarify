# 五场景文本试造远端验证

日期：2026-11-07 14:52（北京时间）。工作单：DCT-004。状态：文本试造与一致性校验完成。

本轮仅执行文本生成与因果格式检查，在 `d6-hpc-debuggpu-001` 的既有 `interclarify-dev` conda（Python 3.10.21）运行。源码通过 GitHub fetch 后创建独立 detached worktree；主仓库保持原工作区，不修改 NTF-054 作业。结构化证据见[验证记录](remote_validation.json)。

## 源码与输出

- 冻结提交：`afd867f6aca2926e454e76378a722da8ee582922`。
- 源码：`/hpc_stor03/sjtu_home/xuan.zhang/parathink-datagen/source/afd867f6aca2926e454e76378a722da8ee582922`。
- 运行目录：`/hpc_stor03/sjtu_home/xuan.zhang/parathink-datagen/runs/dct004-20261107-text-pilot-r1`。
- conda：`/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev`，已检查 `conda-meta/history`。
- 运行目录同级保留 `.log`、`.exit_code`、`.tests.log`、`.tests.exit_code` 与 `.verification.json`。

实际命令使用冻结目录中的 `datagen/run_remote_pilot.sh`，位置参数为上述 conda prefix 与运行目录。生成退出 0；远端同资源限制下的 17 项数据边界测试退出 0；冻结 worktree 校验后仍干净。

## 资源与一致性

| 项目 | 限制／实测 |
| --- | --- |
| 并发与 CPU | 一个工作进程，CPU affinity `[0]`；四类计算线程变量均为 1 |
| 内存 | 地址空间上限 2 GiB；实际峰值 RSS 19,636 KiB，约 19.2 MiB |
| 时间 | CPU 110 秒、墙钟 120 秒；导出器实际执行 0.0809 秒 |
| 磁盘 | 单文件上限 32 MiB，总产物上限 16 MiB；实际产物含执行记录 427,421 字节，约 417 KiB |
| GPU | 未使用 |

三份 SFT 视图、共同轨迹、中文审阅稿的 SHA256 与本地全部一致，`manifest.json` 也逐字节一致，摘要为 `163bb69223c830d28757f849b9837f67fc4c0bec756d559a445f1107a0392d93`。场景源及导出器摘要与清单一致。`execution.json` 反映各机器的真实执行情况，按设计不要求相同。

远端同样得到五个独立来源、13 条轨迹、26／48／16 个展开样本，去重为 18／36／9。这里的耗时仅表示文本导出，轨迹时间仍为模拟；没有语音合成、对齐、冻结前端推理或训练，也不证明思考收益。全部样本仍待独立审核并禁止用于正式训练。
