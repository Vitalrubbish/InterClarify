# TextTurn 数据契约测试

对应文件：`tests/test_textturn_dataset.py`。用小型 ByteLevel tokenizer 做六项 CPU 契约检查，不下载或加载模型。

`TextTurnDatasetTests` 在临时目录创建 tokenizer，验证 Unicode 分片不丢字符、统一末尾句读处理且不留下孤立句读空片、600ms 换成四个 160ms 空窗、仅动作 token 计算损失、未标注记录全屏蔽、未来内容不进入当前输入、自然播放结束不标 stop，以及非法动作／未声明合成文本被拒绝。

助手流检查验证：空 User 观察时助手照常推进；用户到达时双方按同一时钟推进；Assistant 累计前缀逐窗增长，未发布后缀不进 prompt；将步长从 2 改成 1 会改变可见前缀长度。自然完成负例确认最后一片可见后才允许 playback_complete，未发布完时拒绝提前完成。

这些测试验证数据编译合同，不证明语义标签都正确、测试独立或模型质量达标。实际固定 Qwen tokenizer 的往返检查及批次数量另见本轮报告。

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -p test_textturn_dataset.py -v
```
