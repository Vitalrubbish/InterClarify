# 外部评测隔离测试

`tests/test_layer1_exclusions.py`使用unittest构建最小FLEURS/历史Word/FDB目录，检查完整样本数但无文本仍reviewed=false、占位符不当成正文、历史Word完整拼接、覆盖齐备的确定性摘要，以及外部一句话出现在UltraChat多轮中也能被排除。

测试使用临时目录，不下载音频、不产生真实评测覆盖声明。真实727条FDB、100条FLEURS与5例历史材料由远端工具核验。
