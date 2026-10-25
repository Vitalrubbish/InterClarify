# FDB远端串行运行任务

对应 `scripts/remote/run_textturn_fdb.sh`，只用于用户授权的TT-005／006单次作业。

脚本无类。`run_step`建立可清理进程组；`stop_services`停止ASR与控制器；`cleanup`记录退出码并清理服务和运行步骤。所有模型只在调度节点现有conda环境执行，不安装依赖、不复制模型。

启动前检查可用盘至少30GiB、conda元数据和新输出目录；记录源码提交、两环境依赖、清单、预算、基模／tokenizer／Nemotron／adapter及相关源码摘要。adapter必须匹配固定TT-002摘要。

共卡启动Nemotron与控制器，健康后串行运行不进入100条的两条接口冒烟，再运行正式50＋50。冒烟仅按运行契约、候选身份和Context一致性放行。服务停止后离线评分，保留逐例失败和全部计划分母。

一个活动作业，1GPU、8CPU、32GiB，应用层单ASR流、单控制worker，无并行录音。每10秒核对显存22GiB停止线、原TextTurn新增资产10GiB和报告2GiB上限；触限停止并保留结果。外层时长由提交器按实际剩余额度限制在2小时内。

字节总数固定使用无小数整数字符串，避免远端awk将大整数输出为科学计数法，造成bash整数比较失效。r2已通过两臂真实冒烟并进入正式回放，但因发现此监控兼容问题主动停止；原trace保留，修复后使用相同冻结清单独立编号，原占卡仍纳入累计预算。

输出位置为`~/parathink-textturn/runs/<run_id>`；正式trace在`formal/traces`，在线进度在`formal/progress.json`，服务停止后结果在`scoring`。退出码0只代表作业执行结束，不表示模型质量通过或TT-004完成。

TT-007支持`TEXTTURN_FDB_CONFIG`，默认480ms路径不变；复制所选配置到run的`protocol.json`，核对与清单内容及摘要完全一致后再加载模型。回放和评分从同一清单读取周期，不能出现160ms回放却按480ms拍数计分。源码、配置及产物独立冻结，不改正在运行的480ms worktree。
