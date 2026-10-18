# Issue 001 远端核验任务单

状态：进行中。2026-10-18 本地 SSH 初次两次连接超时，重试后成功；只读资产扫描已执行，后续运行时对照仍需单独证据。

先将当前两仓库源码同步到独立目录，记录提交与工作树摘要，不覆盖历史实验。CPU 资产扫描在远端已有 conda 环境执行；全文件哈希可能产生较大存储读取量，串行运行。以下路径来自历史脚本，执行前核实。`--asset` 接受文件或目录，输出目录必须不存在。

```bash
conda run -p /hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-dev \
  python scripts/remote/inventory_layer1_assets.py \
  --repo . --xtalk xtalk \
  --asset official_source=/hpc_stor03/sjtu_home/xuan.zhang/DuplexCascade \
  --asset checkpoint=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28 \
  --asset base=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a \
  --asset nemotron=/hpc_stor03/sjtu_home/xuan.zhang/interclarify-asr-selection/models/nemotron_en \
  --output data/runs/issue001-inventory-UNIQUE
```

另以 `--asset kokoro=<实际目录>` 登记 Kokoro，以同样方式登记真实轨迹与 UltraChat 来源清单。工具记录磁盘事实，不推断模型 revision 或许可结论；逐一核对模型卡、许可、来源 revision、tokenizer、发布配置与 safetensors 参数目录，回填协议配置。缺失文件、读取失败、运行中变化均保留为失败。

GPU 诊断必须通过 `vc` 调度，起步 1×4090、8 CPU、32GB 主存，最多 4 GPU 小时；实际模型主存需求超限时先登记资源调整。复用 `retest_asr_official_input.py`，仅选择 `--configs nemotron_en-160`，保留 original/without_punctuation；旧删除标点函数仅是历史诊断，不作为 004 保护时间、小数等字符的训练增强实现。

运行前仍须实现并冻结独立官方参考执行入口和两路统一事件驱动；当前旧复测入口不能直接产生以下完整矩阵，不得将其运行替代本任务：

| 维度 | 固定范围 |
| --- | --- |
| 输入 | 历史 endpoint-b4d12d6 的五例 EN160 轨迹；另外八种最小协议场景 |
| 场景 | 空拍、词内增量、句中停顿、接话、有效插话、用户附和、连续两轮、reset |
| 时钟 | session-start 与 first-nonempty 分别出表；600ms，串行，无过时拍积压 |
| 发布粒度 | raw 与 complete-word；后者最多暂存 160ms，只用已到达字符；超时刷新，EOF 仅排空，不进入 LLM |
| 排错 | 同 prompt 单步；固定生成输出执行；独立生成历史自由回放，三者分开 |
| 记录 | 逻辑/实测时刻、可见前缀、窗口、请求序号、在途请求、prompt/生成 IDs、控制、正文、取消/reset |

完整词视图必须显式标为诊断，不变更产品发布方式。存在前缀回写时停止该条件并记录不适用原因，不能强行冻结前缀。输入及最小场景须在推理前保存文件哈希。参考代码固定为 `42893024ca90c8de8ac3ed624467ebc123512ff8`，server.py SHA256 见协议配置；任何补丁另存摘要。参考执行不能调用集成路径的 prompt/状态实现。

报告写 `reports/layer1_training/<run_id>/`，大日志留远端；包含双方时间线、首次差异、失败/缺测、退出码、资源、允许差异和通过／修复重测／阻塞结论。原始 EN160 0/5 基线保持历史来源，不伪造新 run。参考缺失、覆盖不足或影响分拍/历史/控制的未解释差异阻断 006，但不阻止离线资产与数据工具准备。
