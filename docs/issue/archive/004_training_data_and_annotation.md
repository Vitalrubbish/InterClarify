# Issue 004：UltraChat micro-turn 数据生成与交付

状态：完成，已归档。日期：2026-10-19。最终run_id：`issue004-build-r5`，源码`7cda3b1`；实现见`b46136b`及`7cda3b1`。最终报告：[r5机器交付](../../../reports/layer1_training/issue004-build-20261019-r5/README.md)。

## 完成依据

用户已审阅r4并反馈无明显问题，随后要求与Nemotron ASR核对缩写、大小写和数值形式；核验020及修订021完成后，用户明确要求删除r4、生成r5，免除本轮人工审查并直接关闭004。r5机器审计通过，构建身份与review记录绑定同一豁免理由，`parent_issue_complete=true`；逐条reviewer/accepted保持空值，未伪造审查通过。r4远端生成目录约631MiB及仓库审计副本已删除。

- [x] 使用固定UltraChat原始来源：`stingning/ultrachat` revision `f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0`，MIT许可元数据、十个shard完整大小/SHA256验真齐全，合计9,288,990,895字节。作者精确50k清单未知，不宣称复用作者完整生成代码。
- [x] 固定种子跨shard有限抽取6000条原始对话，只过滤抽样部分，保留5278候选后按原文及数值规范化后的近重复组切分1000/200/300；不做全库扫描，不主张全库逐对话等概率。
- [x] 外部FDB、历史五例和FLEURS保持隔离；规范化后用户文本也检查已有外部摘要。来源清点reviewed=true，可选FDB文本覆盖缺失仍如实报告false；用户已取消补转写前置要求。
- [x] r5生成5271个监督序列、270730个基础micro-turn；每臂有效监督token总数1780660，三臂共用事件与目标；T3训练视图500/500。32/100训练子集保留供005短跑，不借用dev/test。
- [x] 全量重建1500份计划及全部序列，验证来源映射、特殊token、ChatML、mask、窗口和目标一次覆盖；原始及规范化后跨集合ID/组/近重复均为0。
- [x] 本地与远端conda各34项相关测试通过。远端独立training conda、单CPU/nice10、2GiB虚拟地址空间、目录10GiB、单文件2GiB、总3600秒上限，最终退出0。无GPU训练。
- [x] 用户明确豁免r5新增人工复审，机器报告记录豁免；004关闭，不启动训练，`training_allowed=false`。005零更新/恢复及007开训前准备仍待完成。

## 生成协议与数据契约

用户长轮先按`english_numeric_v1`转换数值为英文读法，再随机抽取1–7基础token。基数/序数、上下文年份、日期/时刻、货币/百分比、电话号码分别处理；月份、大小写和撇号保留，允许ASR中真实存在的词内增量。无法判断月日顺序的日期、不支持的代码/公式/版本/标识等排除整条对话，r5该原因468条。原始完整对话保持不变，plan.user_turns保留原文、规范化文本和逐段替换跨度；user_origin指向规范化字符跨度。T1“原样”为共同数值前处理后保留句读的视图。

去句读后为空的标点独占片段在事件生成前合入相邻片段；r5合并2177次，超过7基础token的最终用户片段286个，作为明确的论文参数例外。所有有来源用户片段两视图均非空。assistant正文直接保留发布tokenizer ID，每片段最多10个正文token，不做数值规范化或删句读。

自然停顿按非末用户片段概率0.10插入1–5空拍，仍监督talking；首回答片段配finish；有下一用户轮且回答至少两片段时按0.30采样有效插话，停止旧回答并消费下一用户轮；回答续写拍按0.01采样附和并继续当前回答；正常回答后加1–20个thinking空拍。具体边界分母、互斥规则与论文未明确部分均如实记录。关闭system backchannel，不新增token、仲裁器或播放所有权。

发布五类控制ID及no-voice、EOS/ChatML逐项核验。所有user/header/重叠历史mask为-100，只有当前assistant目标监督一次；三视图共享合法完整事件窗口，最大4096为数据审计长度，实际训练长度待005冻结。合成时钟不冒充真实ASR到达时间；官方checkpoint可能见过内部文本保留集，原训重叠仍为unknown。

## 原件及后续

远端：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-layer1-training-20261019/data/runs/issue004-build-r5/`。
数据manifest SHA256：`4876c0940379259756c4709fe603cf7a6c9d77bc2248a1a5d1c0abdcad44c5115`。

关联完成单：[018交付](018_layer1_data_delivery.md)、[019空拍修复](019_duplex_data_alignment_audit.md)、[020表面形式核验](020_asr_text_surface_alignment.md)、[021数值修订](021_asr_surface_data_revision.md)。r5-attempt1在候选分组早期因边界规则补充而主动取消，不计为正式交付；最终只认上述r5及摘要。下一步为005/007，004关闭不等于006训练放行。
