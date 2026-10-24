# TextTurn 数据契约测试

对应文件：`tests/test_textturn_dataset.py`。七项单线程CPU检查使用临时ByteLevel tokenizer，不下载或加载模型。

TextTurnDatasetTests覆盖字符往返、句读与Unicode边界、600ms按480ms量化为两窗960ms、连续空窗计数使输入不同、动作损失屏蔽、未标注记录全屏蔽、未来用户与助手文本隔离，以及非法动作、未声明合成文本和未出现停止依据却标stop的记录被拒绝。

助手流检查确认生成步长参数有效；生命周期检查确认生成结束后无新增文本仍可Speak、播放完成才转Listen、随后下一轮等待为Listen/keep，未生成完不能提前播放完成。随机检查确认User的1—2 token分片和随机空窗可复现。实际Qwen tokenizer、全部窗口及播放尾窗打断对照另见本批verification.json。

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
conda run --no-capture-output -n interclarify-dev python -m unittest discover -s tests -p test_textturn_dataset.py -v
```

测试验证数据合同，不证明真实ASR、生成或播放时序及模型质量达标。
