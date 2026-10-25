# TT-010 数据与输出生命周期交付

## v2：歧义keep与专用finish ID

按用户本次明确指令，已交付`artifacts/textturn/tt-010-yield-v2`。原unknown动作改为keep，保持当前Listen／Speak，不新增unknown token；1353个原未监督快照全部追加keep ID并计算动作损失。手写可判定边界和每个stop的控制时刻保持不变，没有额外等待。仅审核元数据保留fallback_keep，模型输入不含该字段。

| 集合 | 来源 | 正式快照 | keep | start | stop | 无动作监督 |
| --- | --- | --- | --- | --- | --- | --- |
| train | 24 | 2401 | 1897 | 336 | 168 | 0 |
| dev | 12 | 1196 | 944 | 168 | 84 | 0 |

`<finish>`已注册为单个special token，ID **151673**。keep/start/stop/no-voice仍为151669／151670／151671／151672。新增标记随真实或明确合成的播放完成事件进入runtime_events，携带output_id等原有字段；仅首次消费携带专用marker，最近终态通过结构化状态持续可见，不反复追加标记。finish不是预测动作，所有输入位置包括ID151673均为-100，仅最后的合法动作ID参与监督。

独立核查验证3597个快照全部只有一个动作目标；Hugging Face AutoTokenizer离线重载后`encode('<finish>') == [151673]`，该ID在special ID列表中，原四个编码不变；72个实际消费finish的正式快照均正确编码并屏蔽该输入位置。全部252个stop的事件时刻与v1逐一相同，432条轨迹的输出闭环通过。新增token边界检查后，TextTurn共41项回归测试通过。

来源清单及来源正文与v1逐字节相同，v1和TT-001全部冻结摘要核对未变；v2保留相同采样分层，避免把歧义改keep时丢掉原前缀覆盖。构造仍为CPU、单进程、线程1、2GiB地址空间、600秒timeout和512MiB磁盘上限；耗时5.992秒，冻结资产约45.8MiB。

此次完成的是tokenizer注册和数据重建，没有修改旧模型embedding或训练候选。manifest明确training_allowed=false；后续获授权训练时需适配新词表、初始化并学习finish输入行，当前旧训练入口不能直接用于v2。旧模型和播放器未替换，真实语音或模型质量结论不变。

| v2资产 | SHA256 |
| --- | --- |
| train.jsonl | `e2b2899e7a01c93caff436040e969006288ccb4ac88c726034d695a1045ca6ea` |
| dev.jsonl | `50652b77676dadf17657960a4a16dbc959b86990404562191a99894f7171ed9d` |
| timelines.jsonl | `9c6f41ccb0f5ab21a68c72d01a462743af0039ce9f837ddf42a68927ece24a1b` |
| tokenizer.json | `8d06f24d6a4f72c68780e1a502ab29250ada639e905c2fa2f655e12235b97020` |
| tokenizer_config.json | `89a171df7d17659cff14b444b2d099c9d1566350885e7bcb470252c91052fedd` |

构造器摘要`66ceacee3ee170b326148eb435dbef3799667b28259f232f3a47546227d1ba8c`；其余摘要见manifest。独立复核结果和脚本保存在v2目录的audit.json／audit_recheck.py，不计入已冻结manifest。下文为v1历史记录，其中unknown屏蔽及非专用finish编码已被v2替代。

## v1历史交付

2026-10-25完成。按用户“启动TT-010”指令，仅在本地既有conda环境中进行CPU构造与核查，无模型训练或GPU作业。新版本位于`artifacts/textturn/tt-010-yield-v1-r2`，旧TT-001全部冻结文件摘要复核未变化。

| 集合 | 来源对话组 | 对照轨迹 | 正式快照 | keep | start | stop | unknown |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train | 24 | 288 | 2401 | 992 | 336 | 168 | 905 |
| dev | 12 | 144 | 1196 | 496 | 168 | 84 | 448 |

unknown全部屏蔽动作损失，不强标keep。来源组来自旧train／dev，保持原切分，test来源组交集为0；没有使用FDB或重测文本。每组构造12种有目的的事件对照，合计432条轨迹、13853条完整前缀标注。不能将432条对照当成432个独立来源。正式采样中的scenario×category机会为1512／756，包含同源相关机会；实际stop机会为168／84，独立来源分母仍为24／12。训练规模未以重复窗口补满10000上限。

正常输出采用普通JSON `kind: finish`输入事件，不注册token、不改变embedding。动作仍为原keep/start/stop，仅当前动作token参与损失。finish由唯一模拟输出执行点在生成结束、末尾内容播放完且960ms尾窗耗尽后产生；80ms停播确认延迟同样为构造值，不是测量结果。原模型、运行时与旧评测合同没有替换。

## 关键样例

以下来自train来源48269；时间为合成控制时钟，完整上下文、前缀与事件见本地`samples.json`及`timelines.jsonl`。

| 轨迹 | 当前可见事实 | 监督／事件 |
| --- | --- | --- |
| ordinary | Speak中当前新增“Add”，尚无stop/pause/wait | 首个可判定非附和前缀stop |
| transition | “Right”短附和；继续到“Right, but use” | 先keep，新增内容可判定接管后stop |
| pretext | 输出已接受start，助手正文仍为空，新增“Add” | stop，不依赖正文非空 |
| tail | 生成已结束、音频尚未完成，新增“Add” | 仍Speak并stop |
| finish | 完整生成后保留两个播放尾窗 | 尾窗keep；完成才finish、Listen |
| finish_first／update_first | 相同时间用户更新与完成，两种事件先后 | finish先发生则Listen；用户先发生则stop，迟到回调过期 |

其余覆盖短附和、无更新、文本不变／旧版本／旧轮、多个start/stop、截断及异常取消。每个输出ID只接受一个终态；504个已接受输出中stop252、finish180、truncated36、error36。错误与截断没有改成正常完成。已生成与已播放文本分别保存；中断后保留用户已听事实。

## 核查结果与限制

5组新增边界测试及全部TextTurn回归合计40项通过。资产独立核查通过3597个正式快照的长度、合法动作与损失屏蔽、完整事件顺序、输出配对及所有旧资产摘要；超长排除为0。252个stop锚点均在首个标注为可判定非附和的有效更新请求上，236个不含停止词。附和keep108窗、重复旧文本keep72窗、生成结束仍Speak的无更新keep396窗，尾窗打断及首次正文前打断各36个机会。以上全部是**构造监督合同核查，不是模型预测率**；unknown与模型误stop不能混入这些分母。

真实验收应分别统计：可判定非附和机会首个可见决策stop率；ASR发布→控制请求→stop返回→真实停播确认延迟；附和、无更新及重复输入的误stop；生成／播放状态一致性；输出ID闭环。歧义前缀与观察不足单列，新旧合同结果不混算。当前只有合成事件，真实Nemotron、识别噪声和实际音频覆盖均为0，不宣称这些能力已通过，也未授权训练。

本次使用`interclarify-dev` conda，单进程、线程1、2GiB地址空间限制、外部600秒timeout，正式构造耗时5.659秒，资产约45.3MiB，低于512MiB上限。首轮`tt-010-yield-v1`保留为未交付草稿，后续补齐尾窗采样、同刻顺序及错误轨迹，以r2为准，不混合统计。

## 资产与复现

[构造入口说明](../../../docs/scripts/training/build_textturn_yield_dataset.md)、[数据合同](../../../docs/dev/TextTurn/asr_update_yield_dataset.md)、[测试说明](../../../docs/tests/test_textturn_yield_dataset.md)。本地资产包括manifest、来源与切分、tokenizer、train/dev快照、完整timelines、prefix_annotations、samples和audit；大文件不进Git。

| 文件 | SHA256 |
| --- | --- |
| train.jsonl | `4bd160d111a2b3c6c478efaa498d781cab4eae4031618fd71b66c09c7a439dd6` |
| dev.jsonl | `853d5ddf87443a6a06a2e78104a4623ea2682f5c65b881779145357132f7a217` |
| timelines.jsonl | `22d7d954ed3f4b45b320bfdc13e7abc76419f6e1adf00c756550820845bcf8dc` |
| split_index.json | `4baf191dcc17b831760532039b626ba7bae82e9e35d01246dba9d0bb057b9015` |

构造器摘要为`ed2a69403d51d9a5bb581b6dbe750b6fd993b0b80d483046255948199ba991bd`。manifest给出其余逐文件摘要。`audit.json`为独立复核结果，位于manifest之外；辅助复核脚本保存在同目录`audit_recheck.py`，不改变冻结资产。训练与开发使用相同的有限手写前缀族，不能据此宣称未见模板泛化；全历史语义去重范围仍继承TT-001局限。
