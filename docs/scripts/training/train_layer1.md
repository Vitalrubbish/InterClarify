# Layer 1 有限训练器

`scripts/training/train_layer1.py`只执行005的离线有限步短跑，复用`layer1_model.py`严格恢复官方权重，不创建产品服务、不控制播放。正式训练入口尚未放行。

`ProbeDataset`核验r5清单、机器审计、tokenizer、子集身份、原始序列及事件摘要，再按指定最大长度从同一计划重新编码；只读取train，不跨对话packing，不截断事件。索引采用固定种子顺序，单进程、无预取worker；checkpoint保存顺序摘要和下一序列位置。读取逐对话缓存，避免将完整数据复制到内存。

`validate_sequence`逐span检查user、消息头和历史mask，assistant目标与input IDs一致，causal shift由Transformers执行。`collate`右侧padding并将padding labels置-100。每次累积先统计目标token数，再按总有效token加权各micro-batch loss，最后裁剪梯度及更新；验证有限loss和梯度。

`save_checkpoint`原子保存112个LoRA张量、AdamW和scheduler状态、Python/NumPy/CPU/CUDA RNG、步数、序列游标及冻结输入身份；仅在optimizer步后保存。`restore_checkpoint`拒绝配置、数据、资产或源码不匹配，恢复状态后才继续取数据。官方没有发布的optimizer状态不伪造。

训练前后对完整模型逐张量摘要，拒绝冻结参数变化及LoRA零变化；结果保存全部可训练参数名、每步序列ID/loss/梯度范数、实际曝光、吞吐、CUDA峰值、进程RSS、保存耗时及干净进程协议生成检查。`compare`核对连续与恢复运行的最终LoRA、optimizer、scheduler、RNG、游标及后半程loss，默认要求完全一致；失败阻断005。

输出目录拒绝覆盖，单run输出限5GiB并保留至少5GiB可用空间。完整模型固定参数仅引用已冻结发布资产，checkpoint不重复保存基础模型和embedding/head；恢复仍须先完整加载官方模型。

`index`子命令仅对全1,000条训练对话重新编码和计数，输出三臂精确序列/token/顺序摘要，不加载模型、不执行训练。`train`仍只允许32/100条短跑。正式单epoch步数为序列数除以有效batch后向上取整；若尾批不足累积数，未来正式入口须处理最后一个部分累积步。
