# Issue 047/048 延迟对照

状态：Pending期间取消，已由r2替代。任务协议见 [Issue 049](../../../docs/issue/archive/049_latency_decomposition_validation.md)。三臂为600ms首段/无缓存、300ms首段/无缓存、300ms首段/有缓存，micro-turn保持600ms，沿用T2_R3_delayed_start与固定25会话。

本地conda：11项Kokoro客户端测试、24项双工运行/协议测试、8项模型服务/缓存测试（包含tiny Qwen真实缓存）及2项分段统计测试通过。真实权重/音频测试留远端调度执行；测试结果尚未生成，不提前填写性能结论。

X-Talk遵循其禁止自行提交的约定，记录基准提交与完整源文件摘要，以独立快照冻结。InterClarify当前其他用户文档修改不纳入本任务源码。未启动训练，不覆盖旧测量。

调度器已接受任务 `job-179251430615923992781-xuan-zhang`，run_id=`latency-047-048-r1`。远端根 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-latency-20261021-r1/`，输出 `data/r1`，日志 `submit_logs/r1.log`。源码包SHA256与224个源文件清单身份见 [source_identity.json](source_identity.json)；传输后摘要一致。此时仅确认已提交，运行结果待回收。

用户提出可能误删源码后检查：224个测试源文件完整，实际缺失为训练manifest引用的资产清单；恢复与重提见 [r2记录](../20261021-r2/README.md)。旧任务未启动，未生成性能数据。

X-Talk改动同时保存在 [xtalk.patch](xtalk.patch)，用于在source_identity登记的基准提交上以 `git apply --unidiff-zero` 恢复；未对X-Talk仓库自行创建提交。
