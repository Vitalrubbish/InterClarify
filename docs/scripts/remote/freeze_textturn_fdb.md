# FDB 抽样与输入冻结

对应 `scripts/remote/freeze_textturn_fdb.py`，属于TT-005／006共用入口，无模型加载、无新增训练数据。

模块无类。`freeze`按`SHA256(seed|subset|sample_id)`排序全部候选，检查音频和全部标注，去除非法资产及完全重复的归一化PCM，每臂选择前50条。后续首条有效候选用于契约冒烟，不进入正式100条；不按模型行为选择。清单保留所有候选、排除理由、原始资产摘要、标注、源时长、发送时长和历史使用披露。`annotations`校验时间段，`digest`分块哈希。

写入前要求候选摘要为64位小写十六进制，避免历史文档抄写错误进入冻结协议。

Smooth冻结`input.wav`和`turn_taking.json`；Pause冻结`input.wav`、`pause.json`和`transcription.json`，该子集没有`turn_taking.json`。音频要求单声道16k、非空、有限值；不隐式重采样。发送时固定float32读取、裁剪、乘32767转小端PCM16，保存原文件和归一化PCM摘要。

已知Smooth全部119条有20261021-r4使用记录；其他历史使用标未知，Pause不能宣称未被项目使用。原会话分组缺失则显式记录不可恢复，不把50条录音称50个独立会话。每文件摘要锁定现有FDB版本；上游提交未知直接披露。

远端在已有conda CPU环境以单线程、2GiB地址空间和明确超时运行。输出目录必须不存在；不足50条时保留冻结结果、返回失败，不换来源。实际入口为`--root .../fdb_v1_0 --config configs/textturn_fdb.json --output <fresh-directory>`。

TT-007通过互斥入口`--baseline-manifest`调用`derive_manifest`，只将原480ms协议替换为160ms协议并记录基线清单摘要、路径和周期。正式样本、全部候选和冒烟条目原样保留；拒绝候选、输入、静音或预算等非周期协议变更。运行时仍逐文件核对原始资产摘要，不重复抽样或复制音频。
