# 独立X2完整词正文

本说明记录016已交付代码。最新NTF-017合同要求80ms回调仅暂存结果，第一帧闭合正文不提前写Context，待本160ms两路均完成后联合提交文本与状态；当前代码尚未迁移。

对应实现：`scripts/runtime/independent_x2.py`，工作单NTF-016。正文来源固定为`x2_streaming_asr`；本模块不接受SoulX状态或控制文字，因此complete和原生reset不会结束或重置ASR。

## 类设计

`ClosedText`只接收真实EOS=2结尾的组，组内禁止LISTEN控制token。使用官方解码及`join_emit_texts`拼接；候选正文若不以前文为前缀，立即失败且不修改已提交正文。只保留已闭合组及当前全文，不复用旧教师的token历史重解码快照。

`IndependentX2`持有一个因果`X2Engine`、最多64个开放组文字token、正文回调和80ms进度回调。调用串行，逻辑session／turn固定；不包含两帧聚合器、发布释放屏障或教师注入。

## 核心方法

`load()`核对既有`configs/x2_streaming_probe.json`完整内容、锁定官方源码摘要与模型权重摘要，按原引擎BF16、英文language-tag和80ms LISTEN／DECODE协议加载。首块用2600合成采样预填充，形状沿用272 mel帧与32左padding帧；实际增量是1680采样、8 mel帧。只复用探针中的因果引擎，不调用旧教师worker。

`step(ledger, step_id)`使用第i帧的`[i×1280−200,(i+1)×1280＋200)`输入。左侧负坐标与EOF右padding显式登记；实际处理截止为1280帧末，观察截止多200真实采样。原生引擎在当前音频步内连续DECODE到真实EOS并同步设备，随后立即交付闭合正文，不等待第二帧、SoulX或160ms屏障。一个组可以包含多个词。

`_token()`维护开放组诊断，WORD不提交，WAIT不生成文字；超过64个文字token直接失败，最多保留64个，不补EOS。无新字WAIT仍交付独立进度。先交正文、再交本帧进度，进度含已闭合组数，后续Context可据此核查提交顺序。正文未变化时不刷新`text_available_at`。

`cancel()`与短回调通过发布锁串行，禁止后续调用及迟到回调；推理中的设备工作须由所属worker收尾，不会并发清理正在使用的KV。`diagnostics()`分别保留已交付正文／组数、引擎已解码正文／组数、开放组、真实进度与失败原因，尾词状态保持unknown。EOF不强制闭合，不额外drain或回填在线正文。

回调使用同进程单调时钟，必须短时返回；NTF-017负责原子Context写入，NTF-020负责complete交接。真实形状、资源和识别质量的远端验证仍属于NTF-018／019。
