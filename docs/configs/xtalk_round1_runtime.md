# `configs/xtalk_round1_runtime.json`

## 整体作用

一份可被 `Xtalk.from_config` 直接实例化的运行配置，把首轮模型组合接成 X-Talk 运行时：本地 Qwen3-ASR 适配器、`DefaultAgent` + 本地 vLLM、`MossTTSRealtime`、`XTurnix`。区别于只做模型准备的 `configs/xtalk_round1.yaml`；X-Talk 的 `from_config` 只接受 JSON，故为 JSON 文件。

## 字段

- `asr.type = Qwen3ASRClient`：X-Talk fork 中符合 `ASR` 契约的本地服务适配器；`base_url` 指向 `qwen3_asr_service.py`（默认端口 8005），`chunk_ms=600` 决定 `stream_chunk_bytes_hint`。
- `llm_agent.type = DefaultAgent`：`model` 指向本地 vLLM（OpenAI 兼容，端口 8000，服务名 `xtalk-round1-llm`）；`extra_body.chat_template_kwargs.enable_thinking=false` 显式关闭 thinking。`backchannel_model`/`backchannel_source_dir` 为 `null`，System Backchannel 关闭。
- `tts.type = MossTTSRealtime`：`base_url` 指向 MOSS 服务（端口 8004），`voices` 提供一份参考音色。
- `turn_detector.type = XTurnix`：指向 XTurnix vLLM 服务（端口 8003）。

端口与 `configs/xtalk_round1.yaml` 的 `services` 一致。参考音色路径为集群上的绝对路径，联调时按实际路径覆盖。
