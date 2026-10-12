# duplex_model_service.py

## 功能与边界

为 X-Talk 的 DuplexRuntimeAdapter 提供官方 DuplexCascade 权重的 raw ChatML 流式推理服务，ASR/TTS 与播放继续由 X-Talk 管理。只在远端 conda 环境和获分配 GPU 上加载模型；本地测试仅覆盖 HTTP 与状态字典契约。

## 类设计与核心方法

OfficialDuplexModel 按 train_cfg.json 加载本地 Qwen2-7B-Instruct，resize token embedding，创建 q/v LoRA 与 embed_tokens/lm_head 保存层，装载官方 model_state.safetensors。共享模型 conda 的旧 fast tokenizer 无法读取官方 tokenizer.json，因此显式使用同目录 vocab/merges 的 Qwen2 slow tokenizer（use_fast=False），保留发布 added token ID 和 ChatML。核验 tokenizer token 单 ID 与权重键，normalize_state_dict 对发布 q_proj/v_proj 的 weight/bias 增加 PEFT base_layer 层级；只做键名迁移并核验映射无碰撞，缺失或不匹配直接失败；CUDA 使用 BF16（24GB 4090 部署参数，区别于官方 demo 未显式指定 dtype 的默认加载），冻结推理、do_sample=False，以实际 im_end ID 结束。

stream 保留模型 special token、stop/length 原因；客户端断开通过 stopping criteria 取消后台生成。服务全局串行锁避免多个会话同时占用模型。GET /health 登记模型目录、token IDs 与加载结果；POST /generate 接收原始 prompt 和 max_new_tokens，输出 NDJSON text、finish_reason 或 error。超过模型上下文时拒绝请求，禁止静默裁剪历史。

## 远端启动

~~~bash
conda run --no-capture-output -n interclarify-dev python scripts/remote/duplex_model_service.py \
  --checkpoint /hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/sbintuitions--DuplexCascade/c3dd51ce9a5a7d27f810ffd5dab309f132a94d28 \
  --base-model /hpc_stor03/sjtu_home/xuan.zhang/interclarify-p0-models/modelscope/Qwen--Qwen2-7B-Instruct/8dce1f8a2d3286a7adf09b977e661350ad67e40a \
  --port 8006
~~~

参考官方仓库 42893024ca90c8de8ac3ed624467ebc123512ff8 的 model.py/server.py。运行不下载模型、不启动训练，记录源码、权重资产和环境版本。显存与延迟需真实 4090 作业验收。
