# 第二轮T2正式训练启动记录

2026-10-20用户取消036短跑并要求直接正式训练。036实现归档，开训前真实模型资源、恢复及推理短跑未执行，协议记录用户豁免；未将这些项目写成通过。

条件`T2_R2_paper_aligned`从完整官方DuplexCascade重新初始化，保持原112个q/v LoRA、2e-5、r5原1,000条T2、2048、batch1/累积2、2,428序列/1,214步/1,193,875监督token。变化只有控制权重1/10/5/2/1和warmup122步，之后线性衰减。

本地conda完成原86项Layer1回归（82通过、4项环境相关跳过），随后对用户豁免与正式入口做针对性回归，9项全部通过。原始输出见[startup/local_layer1_tests.txt](startup/local_layer1_tests.txt)与[startup/local_alignment_tests.txt](startup/local_alignment_tests.txt)。远端作业资源1×4090/8CPU/32GiB、并发1、worker0，任务最长8小时；训练目录5GiB、总目录6GiB、空闲保留5GiB。所有恢复checkpoint保留，首轮产物不覆盖。

启动脚本为`scripts/remote/run_layer1_t2_round2.sh`。正式训练结束后自动干净进程加载最终候选，核对完整参数与生成IDs。FDB重测未提交；037在训练与后续报告完成前保持进行中。

调度器已接收作业`job-179248995834872020112-xuan-zhang`，run_id为`issue037-t2-round2-r1`，冻结源码`cf56856`。独立源码位于训练根`source/cf56856`，未修改远端脏主工作区。新输出为训练根`data/runs/issue037-t2-round2-r1`；精确路径、配置摘要与配额见[submission.json](submission.json)。调度状态Running，已观察到第24/1,214步、游标48/2,428，加权loss为0.7053；每步普通CE、五类计数/NLL及资源均已写出。此时CUDA allocated峰值19.100GiB、reserved峰值约23.005GiB，RSS峰值约15.64GiB；详见[startup/training_snapshot.json](startup/training_snapshot.json)。这是正式训练启动证据，尚无训练完成或候选验收结论。

## 训练结束与测试提交

训练完成1,214步、2,428序列、1,000条train对话；全部112个既有LoRA变化且冻结参数不变，summary通过。完整来源和结果见[training_completion.json](training_completion.json)。

首作业最终退出1：候选加载器在参数摘要及生成IDs核验通过后，生成探针变量覆盖了短跑布尔变量，误报正式候选不可服务。修复只涉及可服务状态标记，未改变训练权重或推理生成；10项针对性回归通过。原退出码及完整错误日志保留，未重训、未覆盖失败证据。

测试作业`job-179249282996234249654-xuan-zhang`已提交，冻结测试源码`3f65d7d`，新输出训练根`data/runs/issue037-t2-fdb-r1`。2×4090/16CPU/64GiB、最长4小时、输出10GiB、空闲保留15GiB，单并发。模型服务必须先用修复加载器重新完整验证最终候选及生成IDs，通过后才可推理。详见[test_submission.json](test_submission.json)。

测试只替换候选；驱动、服务、运行配置与033完全相同，134个X-Talk源文件再次校验，固定25个历史input.wav和70份原始资产逐一核验。结果仍在等待，不将提交或transport PASS视为能力通过。
