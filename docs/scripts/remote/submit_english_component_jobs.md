# 英文组件调度提交

无类。`submit_english_component_jobs.sh` 要求独立 ENGLISH_COMPONENT_ROOT 与唯一 ENGLISH_COMPONENT_TAG，将 ASR/TTS 分别提交单卡 4090、8 CPU、32GB、1800 秒上限的作业。模型分别使用 setup 脚本建立的独立 conda 环境。日志和输出按 tag/backend 隔离；不会启动 LLM 或修改历史运行。完成后必须核对节点 exit_code 和验证 summary，提交成功不能算组件通过。
