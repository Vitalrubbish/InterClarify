# Layer 1 有限训练器

`scripts/training/train_layer1.py`执行005离线有限步短跑，也支持006正式单epoch。复用`layer1_model.py`严格恢复官方权重，不创建产品服务、不控制播放。读取正式配置后，先调用`validate_formal_config`核验技术前置、最终checkpoint选择及预算，失败时不加载模型或创建run目录。030移除dev评测器和自动内容计分的开训要求。B0不能传给训练器。

`ProbeDataset`核验r5清单、机器审计、tokenizer、子集身份、原始序列及事件摘要，再按指定最大长度从同一计划重新编码；只读取train，不跨对话packing，不截断事件。索引采用固定种子顺序，单进程、无预取worker；checkpoint保存顺序摘要和下一序列位置。读取逐对话缓存，避免将完整数据复制到内存。

`validate_sequence`逐span检查user、消息头和历史mask，assistant目标与input IDs一致，causal shift由Transformers执行。`collate`右侧padding并将padding labels置-100。每次累积先统计目标token数，再按总有效token加权各micro-batch loss，最后裁剪梯度及更新；验证有限loss和梯度。

`save_checkpoint`原子保存112个LoRA张量、AdamW和scheduler状态、Python/NumPy/CPU/CUDA RNG、步数、序列游标及冻结输入身份；仅在optimizer步后保存。`restore_checkpoint`拒绝配置、数据、资产或源码不匹配，恢复状态后才继续取数据。官方没有发布的optimizer状态不伪造。

训练前后对完整模型逐张量摘要，拒绝冻结参数变化及LoRA零变化；结果保存全部可训练参数名、每步序列ID/loss/梯度范数、实际曝光、吞吐、CUDA峰值、进程RSS、保存耗时及干净进程协议生成检查。`compare`核对连续与恢复运行的最终LoRA、optimizer、scheduler、RNG、游标及后半程loss，默认要求完全一致；失败阻断005。

026在每个optimizer步结束、CUDA同步后补记当前及累计峰值allocated/reserved、驱动可见free/total和进程峰值RSS，不清缓存、不改变训练计算；设备空闲量是采样值，不能当每个瞬间的最小余量。

输出目录拒绝覆盖，单run输出限5GiB并保留至少5GiB可用空间。完整模型固定参数仅引用已冻结发布资产，checkpoint不重复保存基础模型和embedding/head；恢复仍须先完整加载官方模型。

`record_failure`只向本次调用成功新建的目录写失败记录；若启动时已有输出目录，拒绝后也不覆盖历史failure.json。r1之后补充该失败路径保护及本地回归，不改变已测训练/恢复计算。

`index`子命令仅对全1,000条训练对话重新编码和计数，输出三臂精确序列/token/顺序摘要，不加载模型、不执行训练。005配置仍只允许32/100条短跑；006配置要求`--arm`、1,000条对话、2048窗口/完整1,214步，并把实际重新编码身份与冻结索引逐项核对。`accumulation_count`在正式单epoch末尾允许部分累积，仍按该批实际监督token归一化，不重复、不丢弃目标。

正式训练每203步及最终步保存检查点；中间检查点同样包含全部恢复状态，摘要另存JSON。当前保存步为203/406/609/812/1015/1214，前五个只用于恢复或排错，固定最终1,214步权重用于FDB测试。正式manifest额外冻结协议、正式配置、完整索引、校验器和训练后FDB测试计划，恢复时一并比对；不再访问已移除的`evaluation_assets`字段。每步检查8小时进程预算并保留已有检查点；远端外层timeout负责硬终止。候选干净进程加载及FDB全链路能力报告仍须实际执行。

036新增独立对齐配置入口：沿用首轮数据与参数白名单，显式区分受限短跑和正式训练。加权路径调用`layer1_loss`显式shift；先累计整批权重分母再逐micro-batch反向，并记录普通CE、加权目标、五类计数/NLL。恢复比较包含这些诊断。普通CE原路径不变。
