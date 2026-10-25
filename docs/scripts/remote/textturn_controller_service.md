# TextTurn 影子动作服务

对应 `scripts/remote/textturn_controller_service.py`，属于TT-003。`Controller`只加载已冻结候选及原基模，确认candidate摘要和开发集gate；使用正式prompt及当前状态的两个合法动作分数，不生成回答或解释。`decide`检查输入不超2048 token，返回动作、服务端耗时及token数；超过长度显式失败。

HTTP服务只接受本机影子请求，只有一个推理锁，不修改运行时或播放。客户端负责有界队列、Context先写后读、时间戳及模拟生命周期，单一TTS播放所有权保持原样。所有请求与响应保留候选身份，在线测量须包括客户端调度和传输。

TT-008增加`legal_logits`返回字段，记录当前状态两个合法动作的原始logit；动作仍由同一合法集合argmax产生，没有调整约束或阈值。此字段用于逐例复核stop和keep分数。
