# XTurnix FLEURS 数据测试

`tests/test_xturnix_fleurs_test.py` 用小规模合成 WAV/TSV 验证数据入口，不下载真实 FLEURS，也不替代远端 101 条冻结验收。

覆盖四项：选择规则严格按 `SHA256(filename)` 升序且不足数量时失败；只读复用模式能生成 manifest、历史基线和复核记录；篡改音频后 `verify_manifest` 失败，且未带 `--overwrite` 的重复冻结被拒绝；历史基线常数与来源提交和文档一致。

运行：

```bash
conda run -n interclarify-dev python -m unittest tests.test_xturnix_fleurs_test -v
```
