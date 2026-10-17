# TTS 延迟优化远端任务单

日期：2026-10-17。状态：远端基线作业已提交并通过组件门禁，正在进行真实模型探针与基线回放。已通过交互 PTY 登录 JumpServer：使用现有 `js-hpc` SSH 配置和会话 key，等待菜单后输入 `p`，选择资产编号 `1`（`d6-hpc-debuggpu-001`，`10.24.19.254`），成功进入 `xuan.zhang` 的 shell。直接搜索 `guizhou` 返回“没有资产”；它是用户使用的集群名称，当前堡垒机资产名称不同。必须保持交互 stdin，不能在菜单出现前一次性管道发送多条命令。

已只读确认 `/usr/bin/vc`、共享 `miniconda3/bin/conda`、`xtalk-round1-moss`/`xtalk-round1-client` 环境及 `xtalk-round1/{models,moss-source,moss-service}` 目录存在。远端 `InterClarify` 在 main 且包含未跟踪的历史报告，后续使用独立 checkout，不覆盖现有目录。登录成功不代表 GPU 资源或性能验收已完成。

## 已验证的工具入口

本地 conda `paratalker-dev` 运行完整确定性测试与 WebSocket 协议夹具；`vllm-bench`（torch 2.11.0+cu130，仅 CPU）运行历史惩罚、完整码本对照与单图掩码检查。它与现役 torch 2.9.1 环境不同，不能替代真实 compile 验收。

生成非 FDB 文本集的入口为 `scripts/remote/tts_latency_benchmark.py --prepare-corpus <新JSONL路径>`。基准通过 `--corpus`、`--output`、`--reference`、`--url`、`--repeats` 和 `--server-trace` 接收显式配置。工具已用协议夹具验证，真实服务接入仍待确认。此处不提供未经固定 adapter 远端接入验证的完整提交命令。

## 登录恢复后的准备核对

1. 通过 GitHub 将本分支同步至独立、干净 checkout；禁止覆盖现役目录。保留实际提交、patch SHA256 及模型锁文件。
2. 核对历史共享根 `/hpc_stor03/sjtu_home/xuan.zhang/xtalk-round1` 下的模型、音色、MOSS 源码与 adapter。MOSS 源码必须为 `58b20a0d5fcc6766658d50967a90a9d890009a46`，adapter 必须为 `b3306b97f8a64c1a2f25b9803c070ff32ecff6b1`，二者 `git diff HEAD` 干净；不能假定历史目录仍然存在。
3. 核对实际 TTS conda prefix 与 `configs/xtalk_round1.yaml` 的 `xtalk-round1-moss` 同一环境；客户端使用独立 conda 环境。记录 Python、torch、transformers、flash-attn、模型 snapshot revision 和音色摘要。不升级现役环境。
4. 使用已有 `vc submit` 资源接口申请独占单张 `pdgpu-4090`，记录 GPU UUID、型号、驱动与峰值显存。登录节点只做文件/环境检查，GPU 测试只在分配节点执行。新的节点脚本和提交命令应在拿到真实路径并验证后再固化。

## 实验顺序与环境开关

| 阶段 | 设置与对照 | 必须保留的证据 |
| --- | --- | --- |
| 001 基线 | `XTALK_TTS_TRACE` 指向独立 JSONL；`XTALK_TTS_METRICS=1`；`XTALK_TTS_SEED=17`；batch=0、early=0 | 服务/客户端日志、配置与锁文件、每例 WAV/JSON、冷启动与 warmup 分开 |
| 002 批次 | 原路径与 batch=4 交错对照；仅该变量改变，再根据结果比较 2/6 | token 顺序、首音、batch 帧数、断流、盲试听、取消边界 |
| 003 开头编译 | 沿用 002 已通过配置，仅 `XTALK_TTS_EARLY_COMPILE=1` | 首 1/5/10/50 帧、逐帧 eager/compiled、Dynamo 编译/重编译日志与显存，真实采样数值差异 |
| 004 剩余瓶颈 | 重新读取完整阶段占比后才选一个分支 | 微基准、单变量文本流复测、音质；没有占比证据时保持等待 |

所有实验保留官方采样、音色、ASR/LLM 与话轮设置。每 arm 使用新目录与独立服务 trace，同一 35 条文本，整句/固定增量各 3 轮以上；两模式分别报告。每个 arm 冷启动、图编译、warmup 单列，正式测量前先检查第二个新会话是否热态，避免每会话重编译污染结果。各 arm 分时独占 GPU，交错次序需在节点驱动中固定。

先以工具协议夹具跑通的 `/tts/ws` 路径确认真实 adapter 收到显式 session ID、reference 和结束事件；再通过现有 X-Talk TTS 客户端对同一服务跑 smoke。未接通前不提交完整性能矩阵。若启用 profiler，另跑独立目录，不纳入性能验收。

## 缺项与停止条件

当前工具覆盖 command 队列、文本门槛、prefill/step、生成批次、实际 codec `_decode`、音色准备/缓存、PCM 入队和客户端接收。CPU span 可在同进程分解，CUDA event 单独采样。`gpu.slice` 的共享 backbone event 列表可能含上一轮尚未完成事件，不能据此精确分配逐响应 GPU 占比；未完成 event 保留 pending，不能当作零。

尚缺 socket 实际发送、X-Talk 播放器消费/取消日志、设备播放、GPU 重编译正式计数、首词对齐和人工波形核查。回放器只输出立即消费模拟和 RMS 起点，不代表真人听到时间。报告明确列出缺项；首包均值达标不能替代 p95、失败率、断流和音质。

取消验收须在真实 X-Talk 唯一播放链路覆盖生成中、codec 前后、PCM 已入缓冲及 EOS 附近；本地只验证未提交帧/PCM 的丢弃，不声称覆盖已入客户端缓冲或重复完成事件。组件通过后，冻结 ASR/LLM 做 FDB 小子集；Nemotron 尚未接通、X2 仅供诊断，沉默不得记为优化通过。

没有远端基线与盲试听前，不切换批次默认值，不宣布四项关闭，不启动 KV 复用、codec 编译或 backbone 编译。

## 2026-10-17 远端启动准备

已核对两份 MOSS checkout 的完整提交和 `git diff HEAD` 干净。模型锁记录 TTS revision `75682787d8e2fcc73faca37ba2931453ca9c4022`、codec revision `3cd226ba2947efa357ef453bcad111b6eafba782`，实际 snapshot 为共享 `paratalker-p0-models` 路径；音色为 `xtalk-round1/audio/reference.wav`。原 X-Talk 客户端来自 `xtalk-round1/xtalk@5f0d9959edf1026588246efbed827b078cbb114c`，仅用于组件 smoke，不能当作当前双工 fork 的集成验收。

本轮创建独立 `interclarify-tts-latency-20261017` checkout。新增[节点入口](scripts/remote/run_tts_latency_node_job.md)与[提交入口](scripts/remote/submit_tts_latency_job.md)，先在分配节点检查固定依赖、真实上游等价性，再通过 cold/warm 探针和原客户端 smoke 才运行正式基线。`--probe` 是显式接入检查模式，不替代正式数量门禁；新增理由是必须先确认真实 adapter 接通再投入完整矩阵。脚本按本文已核对路径构造，实际作业结果另记。

首次作业 `job-179219320938398545631-xuan-zhang` 在 `d6-hpc-gpu-068` 上完成依赖核验（torch 2.9.1+cu128 / transformers 5.0.0 / flash-attn 2.8.3），但 42 项组件测试有 1 项失败：作业 `XTALK_TTS_METRICS=1` 污染“无开关时静默”用例。已修正节点脚本，仅在单测子进程显式关闭实验开关，不放宽测试，使用新输出目录重提。首轮无模型性能样本。

第二次作业 `job-179219331247515443792-xuan-zhang` 通过 42/42 组件测试与依赖门禁，MOSS/codec 权重读取完成后启动停滞，180 秒 health 超时，尚无音频样本。补充有界清理和可关闭的 Python 栈诊断，先定位原因，不将此轮作为热态基线。正式汇总另修正为按响应 ID 排除 cold/warm 探针及 smoke，避免启动开销混入阶段分布。

第三次诊断作业 `job-179219357903821135118-xuan-zhang` 取得 Python 和 native 栈：codec 在 `transformers._initialize_missing_keys → _init_weights → torch._weight_norm → GOMP_parallel` 停滞，GPU 空闲。相同节点的隔离 CPU 微基准，单线程 codec 加载 2.123 秒完成，8 线程 25 秒超时（rc=124），仍停留在相同路径；另一个普通 1024×1024 weight_norm 微基准正常，不能泛称所有 OpenMP 运算损坏。

据此新增仅覆盖 codec 加载阶段的独立单线程开关，成功/失败后恢复原推理线程数；不升级依赖、不跳过初始化、不修改权重。这是启动兼容处理，不算首音性能收益。诊断作业不作正式基线，清理后以新目录关闭栈诊断重提。


## 当前作业：20261017-baseline-04

- 作业：`job-179219430342742386259-xuan-zhang`，`pdgpu-4090`，1 GPU / 8 CPU / 32G，源码 `931746b`。
- 实验目录：`/hpc_stor03/sjtu_home/xuan.zhang/interclarify-tts-runs/20261017-baseline-04`。提交日志在同级 `submit_logs/20261017-baseline-04.log`。
- GPU：RTX 4090，UUID `GPU-0c478b82-e50c-7691-2b0a-85113ac35ac1`。
- 设置：batch=0、early=0、官方采样、seed=17、local SDPA + inductor；`TTS_CODEC_LOAD_THREADS=1`，诊断关闭。trace 确认 codec 加载约 9.34 秒（含 `.to(device)`），加载后恢复为 8 线程；此前 2.123 秒为独立 CPU 微基准，二者口径不同。
- 依赖检查通过，真实 MOSS 环境 44/44 组件测试通过；health 200，冷启动长句已生成前 50 帧，编译路径在第 51 帧接管。首次图预热 67.5 秒，属于 cold，不纳入正式热态分布。
- 正式计划：cold/warm 探针与原客户端 smoke 通过后，35 条文本 × 2 种输入模式 × 3 轮 = 210 条正式响应。当前无最终基线或音质结论；002/003/004 不自动启动。

远端 GitHub HTTPS 在本轮出现 Empty reply/连接超时；已用 GitHub SSH 443（`ssh://git@ssh.github.com:443/Vitalrubbish/InterClarify.git`）fetch 并 fast-forward 到指定提交，仍遵循从 GitHub 同步，不复制本地源码或改动固定上游 checkout。

### 已确认正式回放启动

上述作业 cold、warm_one、warm_two 两种模式探针均成功、无空音频；原 X-Talk 客户端 smoke `COMPLETE`，生成 4.4 秒音频、12 个 chunk，参考音色 SHA256 `88cb0b9378829cb398cdaf04cd1e040c1ebce07177e928e788e08bdca7dcfca0`。正式矩阵已写入前 2 条响应，均无失败；尚未生成最终 summary，`exit_code.txt` 未出现，作业仍运行。

预热覆盖问题须单独分析：长句 cold whole 首 PCM 71.722 秒，随后首次短句 warm_one whole 61.068 秒，而第二轮同短句 warm_two whole 0.267 秒、incremental 0.245 秒。每模式仅 1 条探针，且首 PCM 不等于有声起点；这些数值只证明接入与预热行为，不能作为 p95 或优化达标证据。首次换短文本仍有较大图编译/预热开销，提示需要进一步核对输入形状和重编译，尚未证实具体 guard 原因。正式矩阵第一轮可能继续触发新形状编译，必须按轮次与事件区分，不能统称“正式热态”。

查看进展可用 `vc list --job job-179219430342742386259-xuan-zhang`，正式逐响应结果位于 `baseline/responses.jsonl`，最终报告位于 `baseline/summary.json`。当前只启动 001 基线；002/003 的 A/B 与 004 的选择仍待完整结果和质量核验。

## TTS-005 与候选筛选

原作业 `job-179219430342742386259-xuan-zhang` 已完成 210/210，失败/无音频均为 0，`exit_code.txt=0`。基线汇总中 whole 首 PCM p50 0.251 秒、p95 0.713 秒；incremental p50 0.337 秒、p95 0.791 秒。均值受新形状编译的少量长等待影响，后续报告按轮次分开。模拟可听首音明显晚于首 PCM，不能宣称达到 250–350ms 有声目标。

按用户要求新增 [TTS-005](issues/tts_005_sparse_text_prefill_wait.md)，实现可关闭的门槛和原队列超时局部 prefill；默认配置仍保持 processor 门槛和无等待超时。下一作业采用独立 checkout 和[同卡筛选驱动](scripts/remote/tts_latency_experiments.md)，原基线目录保持冻结。筛选的 117 个正式小集合样本不能替代 30 条文本完整验收，原始 WAV、token 接收/消费与编译增量全部保留。

同卡筛选作业已提交：`job-179219646950494824830-xuan-zhang`，源码 `d4056dc`，输出 `/hpc_stor03/sjtu_home/xuan.zhang/interclarify-tts-runs/20261017-screen-01`。独立 checkout 为 `interclarify-tts-screen-20261017`；真实 MOSS 环境 50/50 组件测试通过，control_start 正在按输入预热。驱动顺序与单变量关系见镜像文档。报告生成器另在独立分析 worktree 中运行，不在作业运行中修改其源码。

筛选完成后追加一次独立的 TTS WAV 可懂度诊断：复用远端现有 `interclarify-asr-selection/envs/nemotron_en` 环境（torch 2.11.0+cu128、transformers 5.15.1）和锁定的 `nvidia/nemotron-speech-streaming-en-0.6b@ebe59e5a817142986528bbbee5dba8db7b38ed50` 本地权重，不接入或替换在线 ASR、不安装依赖。模型输入接口依据现有固定权重 README 的 transformers pipeline 用法。另申请单卡作业处理保存的 WAV；作用仅为辅助检查漏词/重复，不能替代隐藏配置名试听或 FDB。

首轮筛选中 `batch4` 完成 18 条，均与配对 control 的 PCM 完全相同；`early_batch4` 首次真实 prefill 因持久历史 buffer 是 inference tensor、返回后在 inference mode 外更新而失败，无音频。保留失败，不视为优化通过。已增加模拟上游 inference-mode 装饰器的完整挂载回归，并修复普通持久 buffer 的创建方式。后续使用独立 checkout / 同卡 batch4 + early_batch4 两臂复测，不修改正在进行的原门槛实验。

离线 ASR 接入探针 `job-179219748134739540386-xuan-zhang` 已完成当时可读的 30 个 WAV（27 control + 3 batch4），无识别服务失败；control 的 sparse 长句转写尾部少 3 词，其输入 token 余量为 0。该现象需要保留用于质量核查，不能仅凭输入 token 完整就宣布生成语音无漏词。最终 ASR 将在全部作业结束后重新覆盖全部正式筛选 WAV。

早期编译修复复测已提交：`job-179219795970912268354-xuan-zhang`，独立 worktree `interclarify-tts-early-fix-20261017@6b41342`，输出 `interclarify-tts-runs/20261017-early-retest-02`，只测 batch4/early_batch4 两臂，共计划 36 条；远端 58/58 组件测试通过。原筛选继续跑 prefill8/4 与 deadline200，不在运行中修改源码。报告必须把原失败与复测结果并列，不能覆盖失败证据或跨卡借用 control。

## 本轮终态与归档

所有 GPU 作业已结束，`vc list` 无本轮活动任务；固定 MOSS 源码/adapter 的 `git diff HEAD` 仍干净。

| 作业 | 来源/退出状态 | 正式记录 |
| --- | --- | --- |
| `job-179219430342742386259-xuan-zhang` | `931746b`，exit 0 | 基线 210，失败/无音频 0 |
| `job-179219646950494824830-xuan-zhang` | `d4056dc`，exit 1 | 原筛选完成 99；旧 early 预热失败，未填零或隐藏 |
| `job-179219795970912268354-xuan-zhang` | `6b41342`，exit 0 | 修复后的 batch4/early 同卡各 18，共 36 |
| `job-179219909689662915563-xuan-zhang` | ASR 诊断，Completed | 135 条 WAV 记录、20 个不同 WAV，识别作业失败 0 |

最终可读报告为 [tts_latency_optimization_report.md](tts_latency_optimization_report.md)，机器可读结果与逐条转写在 `reports/tts_latency/20261017/`。统计始终保留全部尝试；deadline200 有一条正式新图污染，按轮次展开。整体约 1 秒与 TTS 可听预算尚未通过，不变更产品默认参数。

报告通过 JumpServer SFTP 取回并核对 SHA256：虚拟 `/d6-hpc-debuggpu-001/` 对应远端 home，不能直接在 SFTP 中使用 `/hpc_stor03/...`。三组成对试听副本保存在本地 `data/runs/tts_latency/20261017/listening/`，6 个 WAV 均与对应 JSON 的 PCM SHA256 匹配，文件名隐藏配置名，映射单独保存；只是准备试听材料，尚未进行人工试听。

## 组合验证（用户追加）

组合 suite 已提交 `job-179224493766087164069-xuan-zhang`，源码 `6c59aa3`，独立 worktree `interclarify-tts-combination-20261017`，输出 `interclarify-tts-runs/20261017-combination-01`。只运行 control_start / combined / control_end，共计划81条；combined 为4帧批次+早期编译+4-token门槛，200ms等待关闭。配置/规模见工程文档，结果另生成 `docs/tts_combination_validation.md`，不把本次组合与既有单变量实验混成一个分布。原在线ASR和产品默认配置不变。
