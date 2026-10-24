# TextTurn 训练后续评估调度

对应 `scripts/remote/continue_textturn_pipeline.sh`。这是用户已授权训练与后续评估的串行续接入口，不新增issue。登录节点仅执行有超时的轻量轮询及一次vc提交，模型全部运行在计算节点。

等待指定训练run的退出码与candidate；失败、超时或开发集gate拒绝均写停止状态，不自动重训。成功后再次检查vc无其他活动作业，固定源码commit、候选摘要、TTS模型位置，提交一次1GPU/8CPU/32GiB、4h评估。训练实际作业时长与评估上限合计不得超过8GPU小时，轮询每30秒、等待最多4h15min。状态文件保留等待、停止原因或真实调度ID；提交成功不写评估完成。
