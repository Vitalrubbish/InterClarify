# `configs/xtalk_round1.yaml`

用途说明（2026-10-18）：本文说明保留的历史/诊断实现。当前目标已确定为 Nemotron EN 160ms + Kokoro；新组合接入和训练按 [issue 任务](../issue/README.md) 推进，本文参数不代表新组合已部署。

记录保留的通用模型准备与服务参数，由 `run_xtalk_round1.py` 读取，不能直接传给 `Xtalk.from_config`。Qwen3-ASR 已退役，因此不再包含 ASR 模型、源码、环境、服务或修订窗口设置。没有自定义类或方法。

`sources` 固定 X-Talk 历史连接来源及 MOSS 的服务和模型源码；X-Talk 分支名是历史来源标识，不代表启用 Qwen ASR。`models` 只包含 LLM、MOSS 和 codec，`revision=null` 由首次下载解析为不可变 SHA，后续复用 `models.lock.json`。旧锁可以保留额外资产，准备脚本不会为已移除的 ASR 发起下载。

`environments` 与 `dependency_candidates` 固定通用服务的 conda 环境及依赖。`services` 保存分配卡内的逻辑编号、端口、TurnSense ONNX 资产及 MOSS 参数；MOSS 保留 `sdpa` / `inductor` 吞吐补丁。GPU 编号由节点作业覆写，不能当作物理卡号。

`baseline_status` 标识历史连接中的 ASR 已退役；`runtime` 留存历史连接门禁与 600ms 时钟元数据，不是可执行双工配置，也不代表当前选型已验收。X2 诊断运行配置独立位于 `xtalk_duplex_x2_runtime.json`，后续 Nemotron 接入另行验收。
