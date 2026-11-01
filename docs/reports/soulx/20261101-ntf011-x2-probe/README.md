# NTF-011：X2 单帧探针运行记录

## r1：合成自检调用失败，性能门槛尚未测量

源码`37332c3d93df8044c1f5f4575a3d40db7bce20e9`，run `ntf011-x2-probe-20261101-r1`，调度作业`job-179353772137275717780-xuan-zhang`。2026-11-01 20:55:21 CST提交，21:28:07开始，21:29:00结束；退出1。资源为1×4090、4CPU、32GiB，未触发资源停止线。检查时远端队列为空。

| 检查项 | 实际结果 |
| --- | --- |
| 模型／官方推理代码摘要 | 通过 |
| GPU | NVIDIA GeForce RTX 4090 |
| 基础默认处理器 | 9000样本，特征`[1,128,312]`，提示39token |
| 自适应首块 | 2600样本，特征`[1,128,272]` |
| 合成流完整自检 | 失败于首次音频编码调用 |
| 正式用例／60s连续流 | 均未开始，`cases=[]` |
| RTF／积压／漂移／组闭合审计 | 无数据 |
| nvidia-smi设备显存采样峰值 | 8934MiB（仅加载与失败阶段） |
| PyTorch allocated／reserved峰值 | 8457.5／8464MiB |
| 退出码 | 1 |

错误为`TypeError: got multiple values for keyword argument 'use_padding_cache'`。锁定Transformers的`get_audio_features()`已在内部以`use_padding_cache=use_cache`调用编码器，探针又通过`**kwargs`传入同名参数，导致尚未执行音频编码便失败。故本轮是探针集成缺陷，不是模型不满足实时门槛的证据；不能用加载阶段显存宣称稳态12GiB门槛通过。

修复删去外层重复参数，保留`use_cache=True`和实际缓存对象；新增包装器转发及跨步缓存延续的本地回归用例。协议、模型、资源、四条用例与验收阈值均不变。以独立r2重跑，r1不覆盖，NTF-012尚未启动。

## 证据

原始文件已取回至本地`artifacts/soulx/20261101-ntf011-x2-probe-r1/`，含`probe/result.json`、traceback、`probe.log`、显存采样、退出码、冻结清单及源码摘要。远端证据包SHA256：`25b68039a5b907e6bf89497dc13f232b6b98b7c894edcce732ed0d6ccac9dc20`，取回后校验一致。

清单SHA256：`403be34448e0b011fa0b6a26216c0390ea3ed46ce77335e4bbe7a20cdee4f3c07`。
