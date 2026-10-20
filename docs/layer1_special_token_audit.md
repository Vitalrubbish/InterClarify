# Layer 1 special token与论文/发布实现核对

日期：2026-10-20。关联：[040回答启动后移](issue/040_layer1_delayed_response_start.md)。结论：当前使用论文普通版对应的1个用户静音token和5个系统控制token；发布拼写、ID及基本动作映射一致。β系统附和关闭。040改变监督时序，不改变token含义，不能因此宣称仍完整复现论文训练时序。

## 依据

论文[§3.2](https://arxiv.org/html/2603.09180v1#S3.SS2)、[§3.3](https://arxiv.org/html/2603.09180v1#S3.SS3)、[§4.1](https://arxiv.org/html/2603.09180v1#S4.SS1)；官方固定提交`42893024ca90c8de8ac3ed624467ebc123512ff8`的[server.py](https://github.com/sbintuitions/DuplexCascade/blob/42893024ca90c8de8ac3ed624467ebc123512ff8/server.py#L148-L181)。数值ID来自发布tokenizer的已验真资产及实际加载身份，不是论文声明的数值。

本项目核对`configs/layer1_data.yaml`、`configs/layer1_adaptation_protocol.yaml`、`scripts/training/layer1_model.py`、`scripts/remote/duplex_model_service.py`及X-Talk的`protocol.py/runtime_adapter.py`；只读检查，无产品代码修改。

## 六个双工token

| 论文名称 | 发布及当前wire token | 当前ID | 语义与执行 |
| --- | --- | ---: | --- |
| `<no voice>` | `<\|no voice\|>` | 151646 | 用户侧：本拍没有识别到文字；不能直接等同真实无人声，不是让轮信号 |
| `<user is speaking>` | `<\|user is talking\|>` | 151647 | 系统等待；若已处于speaking状态，会按官方逻辑停止当前响应/播放 |
| `<user finish speaking>` | `<\|user finish talking\|>` | 151648 | 判定用户结束、进入回答；允许后接正文，本token本身不保证已有可播放正文 |
| `<user is interrupting>` | `<\|user interruption\|>` | 151650 | 停止旧响应；训练目标为控制后结束该micro-turn；不自动启动新回答 |
| `<user backchannel>` | `<\|user backchannel\|>` | 151651 | 用户附和，继续系统已有回答；不表示系统生成附和语音 |
| `<user is thinking>` | `<\|user is thinking\|>` | 151649 | 系统回答结束后用户思考，系统保持静默；执行侧完成当前文本输入，不撤销已播音频 |

表中转义竖线仅用于Markdown显示；实际wire拼写没有反斜杠。论文叙述中的speaking/talking等拼写差异，由语义映射处理，不通过重命名或新增token解决。

普通版不启用`<system backchannel>`；论文β版为该类增加监督及预合成附和播放。官方普通server的五类列表也不包含该类；代码中残留的`<|assistant_backchannel|>`分支不足以证明当前发布tokenizer包含它，更不能擅自分配ID或启用新动作。

## ChatML与边界

| token | 当前ID | 用途 |
| --- | ---: | --- |
| `<\|im_start\|>` | 151644 | 消息头 |
| `<\|im_end\|>` | 151645 | 当前micro-turn消息结束及生成EOS；不等于用户长话轮结束 |
| `<\|endoftext\|>` | 151643 | 基础tokenizer保留token；当前不插作BOS，不能替代语义finish |

训练与推理均使用官方raw ChatML拼接，assistant历史保留原始生成ID，用户空增量映射no-voice；不调用默认chat_template额外插入system prompt。no-voice和ChatML头均不是系统动作。

## 执行与训练口径

当前wire解析器按生成顺序执行控制，普通正文流入TTS，保留官方推理的宽松处理。论文描述的talking/interruption/thinking通常只有控制及EOS，是训练目标；运行时解析器没有把重复控制、空finish或长度截断全部升级为错误。普通正文续写允许没有新的控制token。确认token设计一致，不代表生成行为必然符合训练目标或全部运行组件与论文相同。

040将最后文字拍监督为talking，下一no-voice拍监督finish＋正文；首插话拍的interruption保持立即执行。两种安排都使用相同token集合。论文未公布足以核验每个边界的完整训练生成器，不能用本项目finish/no-voice频数反推官方频数。

## 本次验证

[核对记录](../reports/layer1_training/issue040-delayed-response-plan-20261020/token_audit.json)逐项比对已验真tokenizer元数据、训练ID、公共加载器六个wire token、X-Talk五类映射、协议关闭系统附和，以及037真实服务的token ID。公开代码和论文核查日期见记录。

本次未改tokenizer、权重、运行配置或X-Talk源码，未提交训练/测试作业。两份顶层设计规范仍保留用户删除状态。
