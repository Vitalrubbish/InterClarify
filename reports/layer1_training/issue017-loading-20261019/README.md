# Issue 017 修复与远端重跑审查

更新：2026-10-20。**GPU入口已修复，真权重零更新通过；136拍服务回归为4/5，017继续进行中，不关闭。** 训练放行保持false，未运行optimizer或梯度更新。完整结论见[机器摘要](review_decision.json)，后续边界分拍问题由[022](../../../docs/issue/022_runtime_replay_boundary_ordering.md)跟踪。

## 最终重跑证据

r4作业`job-179242557114450383845-xuan-zhang`，源码`12d478a`，节点d6-hpc-gpu-053。冻结checkout在训练根`source/12d478a`；两个输出为`data/runs/issue017-zero-update-r4`和`data/runs/issue017-runtime-regression-r4`。训练根为`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019`，独立conda为其`envs/training`；X-Talk仍只读引用001归档快照。原始[调度入口](r4-review/submit/issue017-zero-update-r4.sh)、[作业输出](r4-review/submit/issue017-zero-update-r4.log.txt)和[回收清单/摘要](r4-review/retrieval.json)已保存；完整logits留远端，形状和摘要均已回收。

| 验收项 | 实际结果 | 证据 |
| --- | --- | --- |
| GPU分配 | CUDA_VISIBLE_DEVICES为空，NVIDIA_VISIBLE_DEVICES有效；实际单张RTX 4090、25262096384字节显存、BF16可用 | [预检查](r4-review/issue017-zero-update-r4/gpu_preflight.json) |
| 加载/HTTP契约 | 7项加载、6项服务测试全部通过 | [加载测试](r4-review/issue017-zero-update-r4/loading-tests.txt)、[服务测试](r4-review/issue017-zero-update-r4/service-tests.txt) |
| 发布资产/恢复 | 逐文件摘要通过；453个参数张量strict恢复，无缺失/意外键/shape错误 | [资产](r4-review/issue017-zero-update-r4/comparison/assets.json)、[候选审计](r4-review/issue017-zero-update-r4/comparison/candidate/report.json) |
| 零更新输出 | 15个原001固定prompt，共111个生成token；每步151652维完整词表raw logits，最大绝对误差0，IDs逐例完全一致 | [比较](r4-review/issue017-zero-update-r4/comparison/comparison.json) |
| 参数摘要/白名单 | 两路径453张量摘要一致，零更新前后不变；只开放已有q/v default LoRA A/B的112张量、5046272参数，embedding/head冻结 | [参考摘要](r4-review/issue017-zero-update-r4/comparison/reference/weights.json)、[候选摘要](r4-review/issue017-zero-update-r4/comparison/candidate/weights.json) |
| 服务回归 | 五例28/26/26/28/28拍，共136拍；第1/2/3/5例一致，第4例有prompt差异，阶段退出1 | [回归摘要](r4-review/issue017-runtime-regression-r4/comparison/summary.json) |

本地已核对回收报告：注册配置/源码摘要一致；15个prompt与001原始请求索引、IDs和来源摘要匹配；两条恢复路径权重摘要相同，logits产物摘要逐例相同。未以新模型结果重选prompt，未放宽BF16/64-token贪心、atol0.02/rtol0.01或IDs完全一致标准。

## 回归失败与关闭决策

[第4例原始记录](r4-review/issue017-runtime-regression-r4/comparison/historical-4-independent_free_replay.json)的首处分歧是request=5（第6次请求）、prompt_token_ids偏移71。此前5次prompt与输出一致；当拍生成IDs也一致，但参考路径用户片段为` bathroom with like`，集成路径为` bathroom with like the`。两边下一拍分别纳入`the steam`和`steam`，说明首处分歧发生在词事件分拍，而非已观察到的同prompt数值差异。

首个非空Word时间0.8120505698秒，名义第6拍4.4120505698秒；`the`记录到达4.4136404991秒，相差约1.59ms。参考实际请求记录在4.4147777241秒，日志未记录两边实际入队与截窗时刻，因此只能支持边界调度顺序的排查方向，尚不能断言纯回放器抖动或排除运行时缺陷。保持本次失败，不通过反复重试挑选成功结果，不修改001原报告、不更换输入或调宽验收标准。022需先补齐实际时序证据并界定责任，再修复与重新完成五例回归；017当前不能归档。

## 资源与边界

申请保持1×24GiB4090、8CPU、32GiB物理主存，最多1个GPU作业；各轮均在前一任务退出后提交。r4零更新252.03秒、回归256.38秒，总508.41秒，小于2400秒；零更新退出0，回归退出1。Python resource记录的子进程峰值RSS分别7388396/7406820KiB（不是整个cgroup内存峰值）；零更新两路径各峰值CUDA分配17592070144字节，约16.38GiB。两输出占用合计135133KiB，约132MiB，小于5GiB。

详见[零更新资源](r4-review/submit/issue017-zero-update-r4-resources.json)及[回归资源](r4-review/submit/issue017-runtime-regression-r4-resources.json)。资源统计使用训练conda中的subprocess/resource/time，已验证退出码透传和JSON记录；没有加载模型到本地或调试机。

## 修复与失败保留

| 轮次 | 作业/源码 | 结果与处理 |
| --- | --- | --- |
| r1 | job-179239981090839983547-xuan-zhang / dfd36d3 | CUDA_VISIBLE_DEVICES检查误拒绝集群NVIDIA_VISIBLE_DEVICES，退出2；[原件](r1-review/retrieval.json) |
| r2 | job-179242512241984503787-xuan-zhang / 493404b | 真实GPU检查、7+6测试及资产核验通过；28GiB虚拟地址限制使第二个base分片mmap失败，退出1；[原件](r2-review/retrieval.json) |
| r3 | job-179242541424100807674-xuan-zhang / 12d478a | 提交命令使用容器不存在的/usr/bin/time，入口未执行、退出127；[原件](r3-review/retrieval.json) |
| r4 | job-179242557114450383845-xuan-zhang / 12d478a | 零更新通过，服务回归4/5，保留差异并登记022；[原件](r4-review/retrieval.json) |

入口先安装退出处理再验证环境；兼容两种GPU可见性变量并验证真实CUDA单卡/BF16，不覆盖设备编号。移除28GiB虚拟地址限制以允许CUDA地址预留和safetensors映射，物理主存仍受调度器32GiB硬限。bash语法、无分配退出2并保留日志、旧输出不被覆盖均已验证。代码与[同路径说明](../../../docs/scripts/remote/run_layer1_zero_update.md)同步。

先前远端CPU小张量及依赖恢复证据保留：[加载测试](loading_tests.txt)、[HTTP测试](service_tests.txt)、[CPU资源](cpu_contract.json)、[HTTP资源](service_contract.json)、[依赖安装](test_dependency_install.txt)、[依赖版本](dependency_versions.json)。004已按r5机器审计及用户授权关闭；005仍待训练器、梯度/保存恢复短跑，006和007前置条件不因零更新通过而自动满足。
