# 五场景与三模块 SFT 监督视图

所有时间、状态与播放均为模拟。候选标签待独立审核；损失边界尚未转换为 tokenizer 标签。

## scene01：翻译：正常交接与重复 complete

用户说“把谢谢翻译成英文”。包含空闲、连续说话、歧义停顿、转写尾词晚发布、一次作答及重复 complete。

### 分支 `normal`

只回答一次，无需启动 Layer 2。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 0 | frontend / p0 | ；状态 user_idle；有效 complete=False |
| 320 | frontend / p1 | 把谢谢翻译成；状态 user_nonidle；有效 complete=False |
| 640 | frontend / p2 | 把谢谢翻译成；状态 user_incomplete；有效 complete=False |
| 800 | script / hidden_tail | {"script_text":"英文","visibility":"audit_only_audio_not_synthesized"} |
| 960 | frontend / p3 | 把谢谢翻译成英文。；状态 user_complete；有效 complete=True |
| 1080 | output / g1 | Thank you.；阶段 generated；实际听到= |
| 1120 | output / q1 | Thank you.；阶段 submitted；实际听到= |
| 1160 | output / s1 | Thank you.；阶段 synthesized；实际听到= |
| 1200 | output / play1 | Thank you.；阶段 playing；实际听到=Thank |
| 1280 | frontend / p4 | 把谢谢翻译成英文。；状态 user_complete；有效 complete=True |
| 1440 | output / done1 | Thank you.；阶段 closed；实际听到=Thank you. |

**soulx 监督视图**

- `c_idle`：输入构造于 20 ms；读取 `p0`，分析 无。目标 `{"user_state":"user_idle"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_active`：输入构造于 360 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_nonidle"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_pause`：输入构造于 680 ms；读取 `p2`，分析 无。目标 `{"user_state":null}`。仅凭文本无法确定停顿是否结束；不确定状态目标损失为零。
- `c_complete`：输入构造于 980 ms；读取 `p3`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_idle`：输入构造于 40 ms；读取 `p0`，分析 无。目标 `{"action":"wait"}`。静音不等于有效 complete。
- `l_partial`：输入构造于 400 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。当前文字不全，继续倾听。
- `l_before_publish`：输入构造于 880 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。尾词虽在隐藏剧本中出现，但尚未联合发布，禁止使用。
- `l_answer`：输入构造于 1000 ms；读取 `p3`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"Thank you."}`。当前有效 complete 已读到，生成一次普通回答。
- `l_duplicate`：输入构造于 1320 ms；读取 `p4`，分析 无。目标 `{"action":"wait"}`。同一 response_key 已回答，重复 complete 不再生成。

**layer2 监督视图**

本分支没有活动思考调用，不虚构 Layer 2 生成样本。

## scene02：会议提醒：首音前与已播后取消

两个分支共享最初的合法回答；模型不预知周五将改成周六。实际播放分支保留已听事实，未播分支合并用户片段。

### 分支 `before_audio`

用户改为周六；旧回答在首音前取消。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 800 | frontend / p1 | 帮我写一条周五开会的提醒。；状态 user_complete；有效 complete=True |
| 920 | output / g1 | 提醒大家，会议安排在周五。；阶段 generated；实际听到= |
| 960 | output / q1 | 提醒大家，会议安排在周五。；阶段 submitted；实际听到= |
| 1000 | output / s1 | 提醒大家，会议安排在周五。；阶段 synthesized；实际听到= |
| 1120 | frontend / p2 | 改成周六，；状态 user_nonidle；有效 complete=False |
| 1140 | runtime / stop1 | {"event":"cancel_requested","output_id":"o1"} |
| 1200 | runtime / closed1 | {"event":"cancel_confirmed","grouping":"merge_user_segment","heard_any":false,"output_id":"o1"} |
| 1520 | frontend / p3 | 帮我写一条周五开会的提醒。改成周六，内容还是提醒大家开会。；状态 user_complete；有效 complete=True |
| 1640 | output / g2 | 提醒大家，会议安排在周六。；阶段 generated；实际听到= |
| 1800 | output / play2 | 提醒大家，会议安排在周六。；阶段 playing；实际听到=提醒大家，会议安排在周六。 |

**soulx 监督视图**

- `c_first`：输入构造于 820 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_interrupt`：输入构造于 1160 ms；读取 `p2`，分析 无。目标 `{"user_state":"user_nonidle"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_second`：输入构造于 1540 ms；读取 `p3`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_first`：输入构造于 840 ms；读取 `p1`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"提醒大家，会议安排在周五。"}`。当前有效 complete 已读到，生成一次普通回答。
- `l_cancelled`：输入构造于 1240 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。取消已确认，用户仍在补充；不续播旧正文。
- `l_recover`：输入构造于 1560 ms；读取 `p3`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r2","text":"提醒大家，会议安排在周六。"}`。首音前取消，用户片段合并；不声称用户听过旧回答。

**layer2 监督视图**

本分支没有活动思考调用，不虚构 Layer 2 生成样本。

### 分支 `after_audio`

用户改为周六；旧内容已播后停止。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 800 | frontend / p1 | 帮我写一条周五开会的提醒。；状态 user_complete；有效 complete=True |
| 920 | output / g1 | 提醒大家，会议安排在周五。；阶段 generated；实际听到= |
| 960 | output / q1 | 提醒大家，会议安排在周五。；阶段 submitted；实际听到= |
| 1000 | output / s1 | 提醒大家，会议安排在周五。；阶段 synthesized；实际听到= |
| 1040 | output / play1 | 提醒大家，会议安排在周五。；阶段 playing；实际听到=提醒大家，会议安排在周五 |
| 1120 | frontend / p2 | 改成周六，；状态 user_nonidle；有效 complete=False |
| 1140 | runtime / stop1 | {"event":"cancel_requested","output_id":"o1"} |
| 1200 | runtime / closed1 | {"event":"cancel_confirmed","grouping":"new_user_segment","heard_any":true,"output_id":"o1"} |
| 1520 | frontend / p3 | 改成周六，内容还是提醒大家开会。；状态 user_complete；有效 complete=True |
| 1640 | output / g2 | 改为周六：提醒大家，会议安排在周六。；阶段 generated；实际听到= |
| 1800 | output / play2 | 改为周六：提醒大家，会议安排在周六。；阶段 playing；实际听到=改为周六：提醒大家，会议安排在周六。 |

**soulx 监督视图**

- `c_first`：输入构造于 820 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_interrupt`：输入构造于 1160 ms；读取 `p2`，分析 无。目标 `{"user_state":"user_nonidle"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_second`：输入构造于 1540 ms；读取 `p3`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_first`：输入构造于 840 ms；读取 `p1`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"提醒大家，会议安排在周五。"}`。当前有效 complete 已读到，生成一次普通回答。
- `l_cancelled`：输入构造于 1240 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。取消已确认，用户仍在补充；不续播旧正文。
- `l_recover`：输入构造于 1560 ms；读取 `p3`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r2","text":"改为周六：提醒大家，会议安排在周六。"}`。已播内容保留并衔接更正日期。

**layer2 监督视图**

本分支没有活动思考调用，不虚构 Layer 2 生成样本。

## scene03：安排整理：系统附和与用户附和

同一对话包含可选听者附和、重复抑制、避免错误赞同，以及系统表达时的用户“嗯，对，你继续”。

### 分支 `backchannels`

附和与打断分别标注；无需思考调用。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 320 | frontend / p1 | 我把这周的安排说一下，你听着就行。；状态 user_nonidle；有效 complete=False |
| 480 | output / bg | 嗯，我在听。；阶段 generated；实际听到= |
| 560 | output / bp | 嗯，我在听。；阶段 closed；实际听到=嗯，我在听。 |
| 640 | frontend / p2 | 我把这周的安排说一下，你听着就行。先准备材料，；状态 user_nonidle；有效 complete=False |
| 880 | frontend / p3 | 我有点想把所有安排都取消，不过还没有决定。；状态 user_nonidle；有效 complete=False |
| 1120 | frontend / p4 | 还是先准备材料，再安排周五会议。帮我整理一下。；状态 user_complete；有效 complete=True |
| 1280 | output / g1 | 先准备材料，再安排周五会议。；阶段 generated；实际听到= |
| 1440 | output / play1 | 先准备材料，再安排周五会议。；阶段 playing；实际听到=先准备材料， |
| 1600 | frontend / p5 | 嗯，对，你继续。；状态 user_backchannel；有效 complete=False |
| 1880 | output / done1 | 先准备材料，再安排周五会议。；阶段 closed；实际听到=先准备材料，再安排周五会议。 |

**soulx 监督视图**

- `c_story`：输入构造于 340 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_nonidle"}`。候选状态仅按当前前缀编写，待独立音频审核。
- `c_user_backchannel`：输入构造于 1640 ms；读取 `p5`，分析 无。目标 `{"user_state":"user_backchannel"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_backchannel`：输入构造于 400 ms；读取 `p1`，分析 无。目标 `{"action":"speak","purpose":"backchannel","response_key":"b1","text":"嗯，我在听。"}`。用户明确要求倾听；存在可选附和机会，不把不发声记为错误。
- `l_suppress`：输入构造于 680 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。刚刚已附和，继续听，不重复短回应。
- `l_no_agreement`：输入构造于 920 ms；读取 `p3`，分析 无。目标 `{"action":"wait"}`。用户尚未决定，不能以“对，就全取消”形成错误赞同。
- `l_order`：输入构造于 1200 ms；读取 `p4`，分析 无。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"先准备材料，再安排周五会议。"}`。当前有效 complete 已读到，生成一次普通回答。
- `l_keep_expression`：输入构造于 1680 ms；读取 `p5`，分析 无。目标 `{"action":"wait"}`。用户为非打断性附和；不增加重复正文，不停止现有播放。wait 表示本边界不生成新文本。

**layer2 监督视图**

本分支没有活动思考调用，不虚构 Layer 2 生成样本。

## scene04：复试通知：共享前缀、澄清与晚到分析

五个续说分支共享类别未知的前缀与首次分析。a1 仍依据旧 p1；分支信息 p2 在它发布前到达。当前用户事实与分析的依据分别保留。

### 分支 `self_resolved`

不过我报的是专硕，我直接念后面的专业学位部分。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 100 | frontend / p1 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。；状态 user_nonidle；有效 complete=False |
| 160 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 640 | frontend / p2 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。不过我报的是专硕，我直接念后面的专业学位部分。；状态 user_nonidle；有效 complete=False |
| 800 | analysis / a1 | 报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。 |
| 830 | controller / control_published | {"basis_frontend":"p2","judgment":{"intervention":"continue_listening","user_state":"user_nonidle"},"protocol_scope":"future_cot_control"} |
| 1120 | analysis / a2 | 已明确报考专业学位，阅读方向同步转向专业学位。两类专属条款不同的事实仍有效，原类别缺口已经消解。 |

**soulx 监督视图**

- `c_shared`：输入构造于 440 ms；读取 `p1`，分析 无。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。分支差异尚未可见，使用一致判断，不提前知道用户类别。
- `c_after_branch`：输入构造于 820 ms；读取 `p2`，分析 ['a1']。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。用户已自行补足类别；旧分析中的“尚未明确”已过期。

**layer1 监督视图**

- `l_request`：输入构造于 120 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。类别缺口可能影响后续资料适用性，先请求分析，无需开口。
- `l_task_active`：输入构造于 300 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。已有活动任务，不为每个窗口重复请求。
- `l_before_analysis`：输入构造于 720 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。本次输入构造早于 a1 发布；即使生成结束前结果到达也不追记。
- `l_after_analysis`：输入构造于 840 ms；读取 `p2`，分析 ['a1']。目标 `{"action":"wait"}`。用户已自行补足类别；旧分析中的“尚未明确”已过期。

**layer2 监督视图**

- `a_first`：输入构造于 180 ms；读取 `p1`，分析 无。目标 `{"analysis":"报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。"}`。本次只读到共同前缀，不能预知用户类别。
- `a_update`：输入构造于 880 ms；读取 `p2`，分析 ['a1']。目标 `{"analysis":"已明确报考专业学位，阅读方向同步转向专业学位。两类专属条款不同的事实仍有效，原类别缺口已经消解。"}`。同一活动任务在后续短推理边界读取新观察并更新依据。

### 分支 `relevant_long`

我报的就是学硕，学硕部分有十几条，我逐条念。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 100 | frontend / p1 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。；状态 user_nonidle；有效 complete=False |
| 160 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 640 | frontend / p2 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。我报的就是学硕，学硕部分有十几条，我逐条念。；状态 user_nonidle；有效 complete=False |
| 800 | analysis / a1 | 报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。 |
| 830 | controller / control_published | {"basis_frontend":"p2","judgment":{"intervention":"continue_listening","user_state":"user_nonidle"},"protocol_scope":"future_cot_control"} |
| 1120 | analysis / a2 | 用户报考学术学位；当前长篇内容属于适用类别，类别缺口消解。 |

**soulx 监督视图**

- `c_shared`：输入构造于 440 ms；读取 `p1`，分析 无。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。分支差异尚未可见，使用一致判断，不提前知道用户类别。
- `c_after_branch`：输入构造于 820 ms；读取 `p2`，分析 ['a1']。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。长篇内容仍然相关，不因为长就插话。

**layer1 监督视图**

- `l_request`：输入构造于 120 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。类别缺口可能影响后续资料适用性，先请求分析，无需开口。
- `l_task_active`：输入构造于 300 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。已有活动任务，不为每个窗口重复请求。
- `l_before_analysis`：输入构造于 720 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。本次输入构造早于 a1 发布；即使生成结束前结果到达也不追记。
- `l_after_analysis`：输入构造于 840 ms；读取 `p2`，分析 ['a1']。目标 `{"action":"wait"}`。长篇内容仍然相关，不因为长就插话。

**layer2 监督视图**

- `a_first`：输入构造于 180 ms；读取 `p1`，分析 无。目标 `{"analysis":"报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。"}`。本次只读到共同前缀，不能预知用户类别。
- `a_update`：输入构造于 880 ms；读取 `p2`，分析 ['a1']。目标 `{"analysis":"用户报考学术学位；当前长篇内容属于适用类别，类别缺口消解。"}`。同一活动任务在后续短推理边界读取新观察并更新依据。

### 分支 `unknown_long`

这部分有十几条，我先念考核，再念材料和成绩计算。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 100 | frontend / p1 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。；状态 user_nonidle；有效 complete=False |
| 160 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 640 | frontend / p2 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。这部分有十几条，我先念考核，再念材料和成绩计算。；状态 user_nonidle；有效 complete=False |
| 800 | analysis / a1 | 报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。 |
| 830 | controller / control_published | {"basis_frontend":"p2","judgment":{"intervention":"clarification_opportunity","user_state":"user_nonidle"},"protocol_scope":"future_cot_control"} |
| 960 | output / cg | 先确认一下，你报的是学硕还是专硕？；阶段 generated；实际听到= |
| 1040 | output / cp | 先确认一下，你报的是学硕还是专硕？；阶段 closed；实际听到=先确认一下，你报的是学硕还是专硕？ |
| 1120 | analysis / a2 | 报考类别仍未知，接下来的多组专属条款依赖类别；当前尚不能确认学术学位条款适用。 |

**soulx 监督视图**

- `c_shared`：输入构造于 440 ms；读取 `p1`，分析 无。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。分支差异尚未可见，使用一致判断，不提前知道用户类别。
- `c_after_branch`：输入构造于 820 ms；读取 `p2`，分析 ['a1']。目标 `{"intervention":"clarification_opportunity","user_state":"user_nonidle"}`。类别仍未知且用户准备长篇展开；语义边界存在，单列未来澄清机会。

**layer1 监督视图**

- `l_request`：输入构造于 120 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。类别缺口可能影响后续资料适用性，先请求分析，无需开口。
- `l_task_active`：输入构造于 300 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。已有活动任务，不为每个窗口重复请求。
- `l_before_analysis`：输入构造于 720 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。本次输入构造早于 a1 发布；即使生成结束前结果到达也不追记。
- `l_clarify`：输入构造于 840 ms；读取 `p2`，分析 ['a1']。目标 `{"action":"speak","purpose":"clarification","response_key":"clarify1","text":"先确认一下，你报的是学硕还是专硕？"}`。独立未来生成边界，不伪造 complete，不作为当前可执行协议。
- `l_no_repeat_clarify`：输入构造于 1200 ms；读取 `p2`，分析 ['a1', 'a2']。目标 `{"action":"wait"}`。同一缺口已经问过，等待用户回应，不重复澄清。

**layer2 监督视图**

- `a_first`：输入构造于 180 ms；读取 `p1`，分析 无。目标 `{"analysis":"报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。"}`。本次只读到共同前缀，不能预知用户类别。
- `a_update`：输入构造于 880 ms；读取 `p2`，分析 ['a1']。目标 `{"analysis":"报考类别仍未知，接下来的多组专属条款依赖类别；当前尚不能确认学术学位条款适用。"}`。同一活动任务在后续短推理边界读取新观察并更新依据。

### 分支 `short_transition`

学硕部分就这一句，下面马上是专硕要求。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 100 | frontend / p1 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。；状态 user_nonidle；有效 complete=False |
| 160 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 640 | frontend / p2 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。学硕部分就这一句，下面马上是专硕要求。；状态 user_nonidle；有效 complete=False |
| 800 | analysis / a1 | 报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。 |
| 830 | controller / control_published | {"basis_frontend":"p2","judgment":{"intervention":"continue_listening","user_state":"user_nonidle"},"protocol_scope":"future_cot_control"} |
| 1120 | analysis / a2 | 用户即将从很短的学术学位部分转向专业学位部分，类别尚未知。 |

**soulx 监督视图**

- `c_shared`：输入构造于 440 ms；读取 `p1`，分析 无。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。分支差异尚未可见，使用一致判断，不提前知道用户类别。
- `c_after_branch`：输入构造于 820 ms；读取 `p2`，分析 ['a1']。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。即将自然转入另一部分，提前询问增益有限。

**layer1 监督视图**

- `l_request`：输入构造于 120 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。类别缺口可能影响后续资料适用性，先请求分析，无需开口。
- `l_task_active`：输入构造于 300 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。已有活动任务，不为每个窗口重复请求。
- `l_before_analysis`：输入构造于 720 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。本次输入构造早于 a1 发布；即使生成结束前结果到达也不追记。
- `l_after_analysis`：输入构造于 840 ms；读取 `p2`，分析 ['a1']。目标 `{"action":"wait"}`。即将自然转入另一部分，提前询问增益有限。

**layer2 监督视图**

- `a_first`：输入构造于 180 ms；读取 `p1`，分析 无。目标 `{"analysis":"报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。"}`。本次只读到共同前缀，不能预知用户类别。
- `a_update`：输入构造于 880 ms；读取 `p2`，分析 ['a1']。目标 `{"analysis":"用户即将从很短的学术学位部分转向专业学位部分，类别尚未知。"}`。同一活动任务在后续短推理边界读取新观察并更新依据。

### 分支 `self_searching`

我报的类别是……我看一下报名信息。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 100 | frontend / p1 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。；状态 user_nonidle；有效 complete=False |
| 160 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 640 | frontend / p2 | 帮我看看复试通知。通知分学术学位和专业学位，我先从学术学位部分开始念。我报的类别是……我看一下报名信息。；状态 user_nonidle；有效 complete=False |
| 800 | analysis / a1 | 报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。 |
| 830 | controller / control_published | {"basis_frontend":"p2","judgment":{"intervention":"continue_listening","user_state":"user_nonidle"},"protocol_scope":"future_cot_control"} |
| 1120 | analysis / a2 | 用户正在查找报考类别；具体类别尚未得到，缺口仍在。 |

**soulx 监督视图**

- `c_shared`：输入构造于 440 ms；读取 `p1`，分析 无。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。分支差异尚未可见，使用一致判断，不提前知道用户类别。
- `c_after_branch`：输入构造于 820 ms；读取 `p2`，分析 ['a1']。目标 `{"intervention":"continue_listening","user_state":"user_nonidle"}`。当前正在自行检索；既不能抢问，也不能提前标成缺口已消解。

**layer1 监督视图**

- `l_request`：输入构造于 120 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。类别缺口可能影响后续资料适用性，先请求分析，无需开口。
- `l_task_active`：输入构造于 300 ms；读取 `p1`，分析 无。目标 `{"action":"wait"}`。已有活动任务，不为每个窗口重复请求。
- `l_before_analysis`：输入构造于 720 ms；读取 `p2`，分析 无。目标 `{"action":"wait"}`。本次输入构造早于 a1 发布；即使生成结束前结果到达也不追记。
- `l_after_analysis`：输入构造于 840 ms；读取 `p2`，分析 ['a1']。目标 `{"action":"wait"}`。当前正在自行检索；既不能抢问，也不能提前标成缺口已消解。

**layer2 监督视图**

- `a_first`：输入构造于 180 ms；读取 `p1`，分析 无。目标 `{"analysis":"报考类别尚未明确；两类专属要求不同，类别会影响后续条款的适用性。"}`。本次只读到共同前缀，不能预知用户类别。
- `a_update`：输入构造于 880 ms；读取 `p2`，分析 ['a1']。目标 `{"analysis":"用户正在查找报考类别；具体类别尚未得到，缺口仍在。"}`。同一活动任务在后续短推理边界读取新观察并更新依据。

## scene05：装箱：递进求解、纠错与失败恢复

同一装箱任务包含可靠递进、固定已播错误恢复、思考超时及执行失败。独立核验件数、重量和预算。

### 分支 `progressive`

先交付可验证的三件上界，再给最优混合方案；所有用户条件在开口前给齐。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 640 | frontend / p1 | 箱子最多装20kg，预算100元。A每件6kg、25元，B每件8kg、30元，两种都至少一件，怎样装件数最多？；状态 user_complete；有效 complete=True |
| 720 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 1000 | analysis / a1 | 每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。 |
| 1120 | output / g1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。；阶段 generated；实际听到= |
| 1160 | output / q1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。；阶段 submitted；实际听到= |
| 1200 | output / s1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。；阶段 synthesized；实际听到= |
| 1240 | output / play1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。；阶段 playing；实际听到=最多只能装三件， |
| 1640 | analysis / a2 | 三件混合组合中，2A+1B重20kg、花费80元，可行；1A+2B重22kg，不可行。因此最优为2A+1B，共三件。 |
| 1720 | task / task_end | {"reason":null,"state":"completed","task_id":"think1"} |
| 1760 | output / continue1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。选两件A和一件B，正好二十公斤、八十元，达到三件的上限。；阶段 playing；实际听到=最多只能装三件，因为四件至少重二十四公斤，超过容量。 |
| 2200 | output / done1 | 最多只能装三件，因为四件至少重二十四公斤，超过容量。选两件A和一件B，正好二十公斤、八十元，达到三件的上限。；阶段 closed；实际听到=最多只能装三件，因为四件至少重二十四公斤，超过容量。选两件A和一件B，正好二十公斤、八十元，达到三件的上限。 |

**soulx 监督视图**

- `c_task_complete`：输入构造于 660 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_request`：输入构造于 680 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。多约束组合有进一步核验需求，保留不先说空泛进展话术的路径。
- `l_partial_answer`：输入构造于 1040 ms；读取 `p1`，分析 ['a1']。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"最多只能装三件，因为四件至少重二十四公斤，超过容量。"}`。当前有效 complete 已读到，生成一次普通回答。
- `l_no_unarrived_result`：输入构造于 1440 ms；读取 `p1`，分析 ['a1']。目标 `{"action":"wait"}`。分析 v2 尚未发布，不凭最终答案虚构当前可见结果；等待不停止既有播放。
- `l_final_answer`：输入构造于 1680 ms；读取 `p1`，分析 ['a1', 'a2']。目标 `{"action":"continue_expression","output_id":"o1","purpose":"ordinary","text":"选两件A和一件B，正好二十公斤、八十元，达到三件的上限。"}`。在新的输入边界利用实际已注入的增量组合结论。
- `l_no_new_value`：输入构造于 1800 ms；读取 `p1`，分析 ['a1', 'a2']。目标 `{"action":"wait"}`。相同分析没有新增价值，不复述、不重启思考。

**layer2 监督视图**

- `a_upper_bound`：输入构造于 760 ms；读取 `p1`，分析 无。目标 `{"analysis":"每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。"}`。本次只发布件数上界，组合仍待后续计算。
- `a_combinations`：输入构造于 1280 ms；读取 `p1`，分析 ['a1']。目标 `{"analysis":"三件混合组合中，2A+1B重20kg、花费80元，可行；1A+2B重22kg，不可行。因此最优为2A+1B，共三件。"}`。本次短推理在表达开始后才构造输入，继续检验组合；仅为模拟调度证据。

### 分支 `fixed_error_recovery`

固定错误前缀压力样例，单列来源；不声称模型自主先犯错，也不把错误正文作为正向目标。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 640 | frontend / p1 | 箱子最多装20kg，预算100元。A每件6kg、25元，B每件8kg、30元，两种都至少一件，怎样装件数最多？；状态 user_complete；有效 complete=True |
| 720 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 1000 | analysis / a1 | 每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。 |
| 1120 | output / wrong_generated | 一件A和一件B共十六公斤。；阶段 generated；实际听到= |
| 1240 | output / wrong_played | 一件A和一件B共十六公斤。；阶段 playing；实际听到=一件A和一件B共十六公斤。 |
| 1640 | analysis / afix | 单件重量为6kg与8kg，1A+1B实际合计14kg，先前16kg的合计不成立；2A+1B为20kg、80元，可达到三件上限。 |
| 1720 | task / task_end | {"reason":null,"state":"completed","task_id":"think1"} |
| 1840 | output / corrected_playback | 一件A和一件B共十六公斤。刚才的合计应是十四公斤，不是十六公斤。最多可装两件A和一件B，合计二十公斤、八十元。；阶段 playing；实际听到=一件A和一件B共十六公斤。刚才的合计应是十四公斤，不是十六公斤。最多可装两件A和一件B，合计二十公斤、八十元。 |

**soulx 监督视图**

- `c_task_complete`：输入构造于 660 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_request`：输入构造于 680 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。多约束组合有进一步核验需求，保留不先说空泛进展话术的路径。
- `l_correct`：输入构造于 1680 ms；读取 `p1`，分析 ['a1', 'afix']。目标 `{"action":"continue_expression","output_id":"o1","purpose":"ordinary","text":"刚才的合计应是十四公斤，不是十六公斤。最多可装两件A和一件B，合计二十公斤、八十元。"}`。错误来自显式固定前缀，仅作恢复上下文；错误 token 屏蔽损失，纠正已听错误。

**layer2 监督视图**

- `a_upper_bound`：输入构造于 760 ms；读取 `p1`，分析 无。目标 `{"analysis":"每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。"}`。本次只发布件数上界，组合仍待后续计算。
- `a_check_error`：输入构造于 1280 ms；读取 `p1`，分析 ['a1']。目标 `{"analysis":"单件重量为6kg与8kg，1A+1B实际合计14kg，先前16kg的合计不成立；2A+1B为20kg、80元，可达到三件上限。"}`。检查实际生成历史与任务重量，给出变化依据，不写纠正话术。

### 分支 `timeout`

保留已发布 a1；记录任务超时并释放，不自动重试。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 640 | frontend / p1 | 箱子最多装20kg，预算100元。A每件6kg、25元，B每件8kg、30元，两种都至少一件，怎样装件数最多？；状态 user_complete；有效 complete=True |
| 720 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 1000 | analysis / a1 | 每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。 |
| 1280 | task / task_end | {"reason":"simulated_budget_exhausted","state":"timeout","task_id":"think1"} |

**soulx 监督视图**

- `c_task_complete`：输入构造于 660 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_request`：输入构造于 680 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。多约束组合有进一步核验需求，保留不先说空泛进展话术的路径。
- `l_fallback`：输入构造于 1360 ms；读取 `p1`，分析 ['a1']。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"最多装三件。两件A加一件B重二十公斤，花八十元；一件A加两件B超重。"}`。失败不等于用户让轮；当前已有有效 complete，Layer 1 可独立核算，不伪造 v2 或自动重试。

**layer2 监督视图**

- `a_upper_bound`：输入构造于 760 ms；读取 `p1`，分析 无。目标 `{"analysis":"每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。"}`。本次只发布件数上界，组合仍待后续计算。

### 分支 `failed`

保留已发布 a1；记录任务失败并释放，不自动重试。

| 模拟时刻 ms | 事件 | 内容 |
| --- | --- | --- |
| 640 | frontend / p1 | 箱子最多装20kg，预算100元。A每件6kg、25元，B每件8kg、30元，两种都至少一件，怎样装件数最多？；状态 user_complete；有效 complete=True |
| 720 | task / task1 | {"reason":null,"state":"active","task_id":"think1"} |
| 1000 | analysis / a1 | 每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。 |
| 1280 | task / task_end | {"reason":"simulated_worker_failure","state":"failed","task_id":"think1"} |

**soulx 监督视图**

- `c_task_complete`：输入构造于 660 ms；读取 `p1`，分析 无。目标 `{"user_state":"user_complete"}`。候选状态仅按当前前缀编写，待独立音频审核。

**layer1 监督视图**

- `l_request`：输入构造于 680 ms；读取 `p1`，分析 无。目标 `{"action":"request_thinking","task_id":"think1"}`。多约束组合有进一步核验需求，保留不先说空泛进展话术的路径。
- `l_fallback`：输入构造于 1360 ms；读取 `p1`，分析 ['a1']。目标 `{"action":"speak","purpose":"ordinary","response_key":"r1","text":"最多装三件。两件A加一件B重二十公斤，花八十元；一件A加两件B超重。"}`。失败不等于用户让轮；当前已有有效 complete，Layer 1 可独立核算，不伪造 v2 或自动重试。

**layer2 监督视图**

- `a_upper_bound`：输入构造于 760 ms；读取 `p1`，分析 无。目标 `{"analysis":"每件至少重6kg，四件至少重24kg，超过20kg容量，因此件数上限为三件；仍需检验混合组合与预算。"}`。本次只发布件数上界，组合仍待后续计算。
