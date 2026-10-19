# 单卡零更新验证入口

`scripts/remote/run_layer1_zero_update.sh`在受调度的单张4090上执行加载测试、HTTP契约回归和独立真权重零更新对照，无类。先记录环境、源码和设备，再核对冻结资产，在两个干净子进程中串行运行官方参考及候选训练加载；不运行优化器或梯度更新。

## 输入、GPU检查与失败记录

必填LAYER1_ZERO_ROOT、LAYER1_TRAINING_ENV、LAYER1_ZERO_OUTPUT，分别指定冻结源码、独立conda和新输出目录，均使用绝对路径。资产可通过LAYER1_MODEL_HOME/LAYER1_OFFICIAL_SOURCE指定。旧输出存在时退出2，不覆盖原件；创建新目录后立即安装EXIT/TERM/INT处理，因此环境或GPU检查失败也留下exit_code.txt。

GPU检查要求调度器JobID，以及CUDA_VISIBLE_DEVICES或NVIDIA_VISIBLE_DEVICES中的至少一个；不覆盖设备编号。训练conda中的torch实际检查CUDA可用、恰好一张可见RTX 4090、22–25GiB显存范围及BF16支持。gpu_preflight.json保存分配变量与实际设备，gpu-preflight.log保存失败信息；此步骤只初始化CUDA，不加载模型。r4在CUDA_VISIBLE_DEVICES为空、NVIDIA_VISIBLE_DEVICES有效的真实集群容器中已通过。

## 资源与产物

申请8CPU/32GiB物理主存/1×24GiB4090，最大计算线程4、禁core dump。物理主存由调度器cgroup硬限约束，不设置进程虚拟地址空间上限；CUDA地址预留与safetensors文件映射不能按物理RSS计费。原28GiB虚拟地址限制曾阻断r2第二个base分片mmap，已移除，物理预算未扩大。

GPU预检查60秒，两组测试各120秒，零更新命令1500秒，提交时零更新整体timeout1800秒，输出预算5GiB。源码摘要包括加载器、比较器、服务、入口及配置；环境版本、资产摘要、固定prompt、logits及全参数摘要、失败日志和退出码均留存。两个模型串行加载，禁止在调试机加载7B。入口只执行零更新，不能用HTTP替身测试替代真实服务回归。

## 同卡回归与当前状态

提交命令在零更新成功后，以&&串行调用run_layer1_runtime_comparison.sh，另限600秒，总上限2400秒。冻结X-Talk通过只读引用001归档源码提供，使用原生Word清单现路径和source.sha256，不改写001原报告或输入摘要。两个阶段都用独立训练conda中的Python标准库subprocess/resource/time包裹，保存退出码、墙钟、子进程峰值RSS及CPU耗时；无需容器外部/usr/bin/time。该包装已验证退出码透传及JSON记录。

017 r4（源码12d478a）真权重零更新通过，136拍服务回归4/5；第4例毫秒级Word拍界差异由用户按运行时抖动接受，017已关闭归档，022排查取消。原始结果及关闭依据见[审查报告](../../../reports/layer1_training/issue017-loading-20261019/README.md)。005仍待训练器及真实更新/恢复短跑，因此006尚未放行。
