# Issue 001 初始资产核验

远端主机 `d6-hpc-debuggpu-001`，2026-10-18；`inventory-01` 只读扫描退出码 0。`inventory_summary.json` 保留文件 SHA256、远端两仓库工作树状态、安装包版本和完整远端报告摘要。官方参考提交 `42893024ca90c8de8ac3ed624467ebc123512ff8` 与冻结 server.py 一致。

实际 tokenizer 通过远端 AutoTokenizer 加载核验：BOS=None、EOS=151645、词表151652。五类 wire 控制 IDs 为151647–151651，顺序详见 JSON；no-voice=151646。checkpoint 头部共453项，其中 embedding/head 各有 original_module 和 modules_to_save 两套 BF16 [151652,3584]，q/v LoRA A、B 各56项且发布为FP32。必须恢复这些实际张量，不可用基础模型替代；还没有执行完整参数恢复审计或零更新比较。

许可元数据：官方代码和checkpoint各自 LICENSE 为MIT，base LICENSE为Apache2；Nemotron模型卡声明NVIDIA Open Model License，Kokoro冻结模型卡声明Apache2。Kokoro远端snapshot当前仅有config/模型/voice三文件，缺少许可副本。这里仅记录来源，`licenses_reviewed`仍false。

`data_source_manifest.json` 固定 stingning/ultrachat 的 revision、十个train文件的发布LFS SHA256和字段id/data。其来源由 [UltraChat官方项目](https://github.com/thunlp/UltraChat#data) 指向，字段与许可元数据见[冻结数据卡](https://huggingface.co/datasets/stingning/ultrachat/blob/f220fe796ce3ed62fbe1681b45ce6cbc9c6cabe0/README.md)；API和数据卡通过hf-mirror取得并记录证据摘要。没有下载训练正文，不声称取得作者精确50k，004须对实际下载文件验SHA256再使用。

远端当前两仓库落后于本地，含未提交报告/文档；本次只扫描，不拉取覆盖它们。新的实验须使用独立源码归档及逐文件摘要。扫描工具四项本地conda单元测试通过，不等于运行时、ASR/TTS或FDB验收。
