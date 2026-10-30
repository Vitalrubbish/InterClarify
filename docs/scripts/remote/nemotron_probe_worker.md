# 隔离Nemotron探针进程

对应`scripts/remote/nemotron_probe_worker.py`。复用既有`NativeNemotron`与`NemotronService`，在ASR conda中加载锁定本地模型，FP32、lookahead1、两个CPU线程、PyTorch显存比例0.55；复用开发录音完成两次独立会话预热。

通过权限0600的Unix socket提供`create`、`push`、`poll`、`close`、`shutdown`，只在当前作业私有临时目录监听，不开放网络端口。单个活动会话，实时源积压上限12800样本；请求最多1MiB，连接超时5秒，错误返回原始原因。EOF2秒静音沿用既有解码排空合同，结果不得冒充在线文字。

权重和环境只读复用，不升级共享依赖；读事件保留原有版本、实际回调时间和保守音频读取截止，不根据名义160ms构造新边界。
