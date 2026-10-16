# run_asr_endpoint_job.sh

单个独占 GPU 的接话诊断作业。先用固定五例 FDB 音频分别运行五配置 ASR，进程逐一退出后释放显存；随后在既有官方模型 conda 环境中加载 DuplexCascade，复用同一模型串行运行原样／去标点两条件。

此作业可与五个 ASR 扩展分片并行，总 GPU 占用六张，处于八卡配额内。原始 ASR 轨迹和控制重放分目录归档；源码摘要门禁失败即停止。空参考仅用于这个数据集，不与 FLEURS WER 混算。

支持 `ASR_ENDPOINT_EXISTING_ASR` 复用已经成功完成的五配置 FDB 轨迹，不重复识别。官方模型服务在既有 `interclarify-dev` 环境运行，X-Talk 重放在既有 `xtalk-round1-client` 环境运行；服务就绪失败或子进程退出均保留日志。退出时仅终止本作业启动的模型服务。
