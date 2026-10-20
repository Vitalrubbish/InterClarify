# test_duplex_model_service.py

## 功能、类与核心方法

DuplexModelServiceTests 使用 FakeModel 与 FastAPI TestClient 检查实际 wire token、stop 原因、生成 token id、health 模型信息、结构化历史输入与预算校验。`test_history_flattens_to_official_chatml_token_ids` 用桩 tokenizer 验证 `build_prompt_ids` 按官方 header/`<|im_end|>\n`/`<|no voice|>` 展平，并拒绝空历史、非 user 结尾与缺失 id 的 assistant 轮。test_checkpoint_validation 验证严格权重键检查，避免服务带有随机初始化层。测试不加载模型；真实权重与 GPU 推理需远端任务验证。

新增发布 q/v 基础权重键迁移测试，验证原张量不变、键名完整覆盖、映射冲突与未知键拒绝。

官方空白契约：连续两拍 `hello` / ` world` 的实际 prompt 应等价于官方独立 Word 拼接后的 `hello` / `world`；空白拍为 no-voice，词内撇号、标点与内部空格保持原样。BOS 为 None 时不插入，有值时只在历史起点插入一次，assistant 生成 ID 不改写。


Issue001独立参考对照增加generate_ids诊断端点，使用同一权重、锁、精度及生成预算，仅绕过集成history renderer；逐token附带generated_token_id供原版参考解码器消费。产品generate保持原契约，原始IDs越界拒绝；本端点不证明独立checkpoint恢复。

test_prompt_bounds_use_one_vocabulary_lookup用1000个有效ID验证词表仅查询一次，同时保留负ID和上界越界拒绝，防止旧tokenizer上校验开销随prompt长度重复放大。

2026-10-21：PrefixCacheTests 验证前缀命中/改写、容量/字节/TTL淘汰；tiny Qwen 用实际 DynamicCache 检查增量与完整历史生成ID、会话隔离、取消后清除。缺少本地 transformers 时仅跳过 tiny Qwen，远端模型conda必须执行。
