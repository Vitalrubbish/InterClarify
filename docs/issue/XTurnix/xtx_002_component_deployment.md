# XTX-002：冻结 Nemotron 与 XTurnix 服务及控制协议

状态：待实施。依赖：[XTX-001](README.md)。依据：[质量测试计划第 2、3、6 节](../../dev/XTurnix/quality_test_on_fleurs.md)。

## 目标

建立可复现的两组件推理入口，固定 ASR、XTurnix 输入格式、停顿来源和调度参数，为真实时序回放提供协议合同。

## 工作内容

- 只读复用 Nemotron EN 0.6B、EN160、FP32 的现役模型与原生流式服务；核对实际 revision、processor、依赖和 160ms 配置，保留 80ms 输入传输。
- 在独立 conda 环境准备 `xcczach/xturnix-pt`，冻结权重、tokenizer、官方管线源码及依赖；不混入 ZH-Base，不覆盖现役 ASR/TTS/评分环境。
- 使用官方 Listen 状态提示词、累计 user 前缀和两合法动作分数取最大值，仅去除末条用户消息的末尾 Unicode 标点及相邻空白；保存归一化前后的输入。
- 冻结最大上下文、ASR 结果轮询周期、单请求超时和有界缓冲/合并策略；超限、失败与截断必须明确可见，不能静默丢失末次输入。
- 冻结停顿观测方式与参数：若采用 `<|pause|>`，必须来自真实上游分段或因果 VAD；不使用 EOF、文件时长或离线最后 token 锚点。停顿观测不暂停 ASR，不执行播放。
- 使用 dev 串行预热两组件并验证原生输出、去标点、暂停恢复、会话清理和资源峰值。参数在正式测试前锁定，不能用正式子集调 start 阈值。

## 交付

拟建 `scripts/remote/setup_xturnix_env.sh` 与同路径中文说明 `docs/scripts/remote/setup_xturnix_env.md`；冻结配置放 `configs/xturnix_fleurs_test.json`，说明放 `docs/configs/xturnix_fleurs_test.md`。复用原生 Nemotron 服务与官方 XTurnix 接口，不新建文本生成或播放支路。远端保存模型/环境锁、配置和 dev 协议证据。

## 验收

- [ ] 模型及代码有实际 revision/哈希，两个服务可在隔离环境加载和退出。
- [ ] Listen 下仅返回 start/keep，并保留输入版本、合法动作分数及请求关联标识。
- [ ] 停顿来源、阈值、轮询与缓冲参数均已冻结，没有人工补点或 EOF 触发。
- [ ] dev 的请求、返回、暂停和清理可复核；模型推理不在登录节点运行。
- [ ] 峰值在预算内，未升级或覆盖现役环境。

## 资源与边界

准备阶段最多 4 CPU、8GiB RAM、下载并发≤2。推理最多 1×24GiB GPU、8 CPU、32GiB RAM、batch=1，仅 1 个作业和 1 条活动录音、单作业≤4 小时；新增资产累计≤10GiB，不自动加卡。不训练控制器，不注入 thinking 结果，不接入表达/TTS。
