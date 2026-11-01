# X2闭合组教师配置

`configs/x2_teacher_append_only.json`继承NTF-011已验收的模型／源码摘要、首块形状和EOS自适应协议，增加160ms主块、4步发布前瞻、800msPCM积压和报告用RMS=0.001分界。`commit_unit=eos_closed_emit`、`last_word_commit=closed_group_only`表示只提交EOS闭合发射组；基础6帧delay只作来源信息。

源码中首块／增量形状与token映射不调参。状态token、状态阈值和原规则均从冻结SoulX读取；本配置的RTF等单进程阈值属于NTF-011来源记录，同卡正式实验如实报告实际值，并受22GiB／800ms停止线约束。
