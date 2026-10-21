# duplex_model_service.py

## 功能与边界

为 X-Talk 的 DuplexRuntimeAdapter 提供官方 DuplexCascade 权重的 raw ChatML 流式推理服务，ASR/TTS 与播放继续由 X-Talk 管理。只在远端 conda 环境和获分配 GPU 上加载模型；本地测试仅覆盖 HTTP 与状态字典契约。

## 类设计与核心方法

033增加可选`--adaptation <formal-training/checkpoint.pt>`。OfficialDuplexModel先完整恢复官方状态，再调用`layer1_candidate.load_candidate`严格恢复最终LoRA，核验完整训练前/后参数摘要并在干净进程复现保存的生成IDs。健康信息新增`adaptation`条件、摘要和复现结论；不提供参数时明确为B0。raw ChatML、控制/正文协议、取消和播放路径保持原行为。

005训练加载实施将完整权重恢复、键迁移及prompt范围检查提取到 `scripts/training/layer1_model.py`。OfficialDuplexModel构造时调用公共加载器的training=False，再建立原有ChatML字段；模型/health/流式协议不改。旧validate_state_keys/normalize_state_dict/validate_prompt_ids名称继续重导出，已有调用和测试保留。新增统一shape检查在复制前拒收不完整资产，审计语义比原服务更明确；真实服务回归与001受影响对照另留证据，不把此重构自动标为已通过。

OfficialDuplexModel 按 train_cfg.json 加载本地 Qwen2-7B-Instruct，resize token embedding，创建 q/v LoRA 与 embed_tokens/lm_head 保存层，装载官方 model_state.safetensors。tokenizer 与官方 server.py 一致使用 fast 实现（`use_fast=True`）：官方 tokenizer.json 含 `ignore_merges` 等字段，需要 `tokenizers>=0.20`，因此 `interclarify-dev` 已升级到 transformers 4.46.3 / tokenizers 0.20.3 / peft 0.13.2（torch 保持 2.4.1+cu121 未动）。升级前已记录 pip freeze 快照，且实测 fast 与 slow 在本权重上的分词结果完全一致。核验 tokenizer token 单 ID 与权重键，normalize_state_dict 对发布 q_proj/v_proj 的 weight/bias 增加 PEFT base_layer 层级；只做键名迁移并核验映射无碰撞，缺失或不匹配直接失败；CUDA 使用 BF16（24GB 4090 部署参数，区别于官方 demo 未显式指定 dtype 的默认加载），冻结推理、do_sample=False，以实际 im_end ID 结束。

stream 保留模型 special token、stop/length 原因；客户端断开通过 stopping criteria 取消后台生成。服务全局串行锁避免多个会话同时占用模型。GET /health 登记模型目录、token IDs 与加载结果；POST /generate 接收 micro-turn 历史（user 文本与 assistant token id 交替，末条必须是 user）和 max_new_tokens，由 `build_prompt_ids` 用官方 header/`<|im_end|>\n`/`<|no voice|>` 单 ID 展平为 raw ChatML，输出 NDJSON text、token_ids、prompt_tokens、finish_reason 或 error。历史形状非法返回 400；超过模型上下文时拒绝请求，并给出实际 token 数，禁止静默裁剪历史。

历史采用 token id 而非纯文本的原因：实测解码文本无法反推模型实际生成的 id（3000 条随机 id 序列中 1564 条 re-encode 不一致，约 52%），保存 id 才能逐 token 复现官方续写 prompt。

生成调用传入 `num_logits_to_keep=1`：官方 server.py 会为**全部 prompt 位置**materialize LM head logits 再取最后一位，长历史下该张量（约 3GiB）正是上一轮 CUDA OOM 的来源；只保留最后一位在数学上与官方等价（已实测输出 token id 完全一致），同时消除该分配。每次请求记录一行 JSON 日志（prompt_tokens、generated_tokens、finish_reason、耗时、峰值显存），用于事后核对 prompt 增长与显存占用。

## 远端启动

~~~bash
conda run --no-capture-output -n interclarify-dev python scripts/remote/duplex_model_service.py \
  --checkpoint /hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28 \
  --base-model /hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a \
  --port 8006
~~~

参考官方仓库 42893024ca90c8de8ac3ed624467ebc123512ff8 的 model.py/server.py。运行不下载模型、不启动训练，记录源码、权重资产和环境版本。显存与延迟需真实 4090 作业验收。

2026-10-18 官方输入复核：旧实现对非空 user micro-turn 编码原始字符串，会保留累计前缀后缀中的前导空格。官方 Word 接收先 strip 再按拍拼接，因此模型提交边界现在编码 `turn.text.strip()`，不改标点/大小写/词内空白；纯空白仍编码 no-voice。`bos_id` 从 tokenizer 获取，仅非空时在整个历史前加一次。参考格式及复测范围见 [输入对齐复核（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/asr_official_input_retest.md)。

复测的可选 `audit_prompt` 字段默认关闭。开启后生成前的审计消息及最终 NDJSON 记录包含实际传入生成器的 `prompt_token_ids`，供外部 oracle 核对；生产调用不额外返回整段 prompt。health 增加实际 `bos_token_id`，只记录模型元信息，不改变生成。


Issue001独立参考对照增加generate_ids诊断端点，使用同一权重、锁、精度及生成预算，仅绕过集成history renderer；逐token附带generated_token_id供原版参考解码器消费。产品generate保持原契约，原始IDs越界拒绝；本端点不证明独立checkpoint恢复。

Issue001d：结构构建后先移到实际设备，再strict恢复发布state，避免CPU同时驻留两套完整模型；记录base加载、GPU结构、state打开和strict恢复四个阶段的耗时与峰值RSS。无完整恢复则不开HTTP服务，参数映射和实际精度不变。

Issue001e：validate_prompt_ids每个请求只取一次词表大小，之后仍逐ID严格检查上下界。旧tokenizers0.20.3的len可能较慢，禁止在逐token表达式中反复调用。duplex_request日志新增validation_seconds，与原有生成seconds分开，完整请求耗时仍由客户端时间线衡量。

## Issue 048 实现设计（2026-10-21）

服务按显式 session_id 保存有界 DynamicCache；请求开关默认关闭，在线配置显式启用。缓存池管理匹配前缀、会话淘汰、字节/token/会话数上限及 TTL；取出后独占使用，成功结束且实际缓存长度核对通过才归还。历史改写先清空重建，取消或错误丢弃在用缓存。会话释放接口在全局推理锁内执行，不影响其他会话。完整历史与原始生成 ID 仍是事实来源。

stream_ids 仅计算未缓存后缀，attention mask 覆盖全部历史，cache_position 从实际缓存长度起算；generate 最后一个输出可能尚未入缓存，保存时仅登记实际 get_seq_length 对应的 token 前缀。生成统计增加 session/request 标识、匹配 token 数、输入长度、模型首 token 和生成耗时；可选 trace 文件记录请求输入/输出 ID、缓存状态和单调时钟，用于固定请求对照。

## 2026-10-21 数值与生成语义核查

实际继承的Qwen generation_config含repetition_penalty=1.05；即使do_sample=False，贪心选择也在该处理之后执行。不能将原始logit最高值当作最终选择。跨请求缓存保持相同token前缀与位置，但BF16完整/分段计算可产生数值偏差；049的一个输入在重复惩罚后近乎并列，导致首正文不同。051已用实际generate分数及FP32对照确认原因，见[诊断报告](../../../reports/latency/20261021-kv-diagnosis-r2/README.md)。服务参数未因诊断而修改，BF16下不承诺完整重算和缓存增量逐token恒等。
