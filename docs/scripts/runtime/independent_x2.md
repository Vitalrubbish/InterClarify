# 独立X2闭合正文与进度暂存

对应`scripts/runtime/independent_x2.py`。正文固定来源x2_streaming_asr，模块不接受控制文字或SoulX状态，complete及原生reset不会结束X2。NTF-017后80ms回调仅送协调器暂存，不表示Context发布；第一帧闭合正文须等本160ms两路均完成后可见。

## 类与核心方法

`ClosedText`只接受真实EOS=2结尾、内部不含控制token的组，使用官方解码与join规则拼接；候选必须以前文为前缀，否则失败且保留原正文。一个组可以包含多个词。

`IndependentX2`持有因果引擎、当前累计闭合正文及至多64个开放文字token。load核对冻结配置、官方源码和模型摘要，使用既有BF16英文原生80ms引擎。

`step()`对第i帧使用[i×1280−200,(i+1)×1280＋200)的1680采样；左padding与EOF右padding分别记账。WORD触发组内连续DECODE至真实EOS，设备实际同步后记录正文及进度；WAIT无新字也完成本步。回执携带身份、帧号、真实处理／观察截止、当前闭合全文／组数、采样span及实际开始／完成时间。正文变化时更新text_available_at和text_observed_until，无新字时保留原值。

NTF-018将引擎原始结果的深副本保存到回执`decode`中，保留真实LISTEN／DECODE token序列、组闭合延迟和计算时间，供预热覆盖与远端归因使用；该诊断字段不进入SharedContext正文，也不改变EOS提交门槛。

`_token()`保留开放组与decoding诊断；64 token触限直接失败，不补EOS。正文回调先于本帧进度回调，只用于当前批次校验。未闭合组、异常或取消不能产生有效联合提交。

cancel禁止后续调用与迟到暂存，设备收尾由原worker负责；diagnostics明确报告decoded_text／decoded_groups、开放组、真实进度和unknown尾词，不将内部解码数冒充Context已提交数，后者从Context读取。EOF不额外drain或回填在线文字。

首次形状、真实延迟及词尾质量由NTF-018／019远端验证，当前[契约检查](../../tests/test_independent_frontend.md)不加载权重。
