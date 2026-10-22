# X2Q-009 FLEURS 英文子集恢复与冻结

2026-10-22。状态：已完成远端恢复、manifest 生成与独立复核；本阶段不加载模型、不回放、不计算 WER 或 complete 指标。

## 固定输入

| 项目 | 值 |
| --- | --- |
| 数据集 | `google/fleurs` |
| revision | `70bb2e84b976b7e960aa89f1c648e09c59f894dd` |
| 下载入口 | `https://hf-mirror.com`（远端不能直连 Hugging Face；revision 固定） |
| 正式输入 | `en_us/test` 按 `SHA256(filename)` 升序前 100 条 |
| 预热输入 | `en_us/dev` 同规则 1 条，不计入正式 100 条 |
| test 总时长 | 969.26 秒 |
| test 标准化词数 | 2,162（`whisper-normalizer==0.1.12`） |
| 音频处理 | 原始归档字节；16 kHz 单声道；未重采样、未转换声道、未裁剪头尾静音 |

test 首条与末条分别为 `2074231104398719826.wav`、`1277588711703410007.wav`；dev 为 `786465049904960526.wav`。test 与 dev 文件名集合无交集，独立目录保存。

## 远端位置与环境

数据目录：

```text
/hpc_stor03/sjtu_home/xuan.zhang/interclarify-x2-turn-complete/dataset/fleurs_en_us
```

独立 conda：

```text
/hpc_stor03/sjtu_home/xuan.zhang/miniconda3/envs/interclarify-x2-turn-data
```

Python 3.11.17；`huggingface_hub==0.36.2`、`soundfile==0.14.0`、`numpy==2.4.6`、`whisper-normalizer==0.1.12`。运行设置 `PYTHONNOUSERSITE=1`，避免用户级 site-packages 混入。环境记录保存在远端 `interclarify-x2-turn-complete/env/data_environment.json`。

源码入口为 `scripts/remote/x2_turn_complete_test.py`（远端提交 `405563c`），说明见 `docs/scripts/remote/x2_turn_complete_test.md`。

## 恢复与复核结果

`prepare-data` 下载 2 个 TSV 和 2 个音频归档，串行执行（并发 1），从归档只提取选中的 101 个 WAV。事件、数据锁、manifest、报告均保存在数据目录；`verify-data` 重新核对 101 个文件的 SHA256、声道、采样率、帧数、时长、标准化词数、test/dev 路径边界和汇总数，退出码 0。

| 项目 | test | dev |
| --- | ---: | ---: |
| 条数 | 100 | 1 |
| 时长（秒） | 969.26 | 7.80 |
| 标准化词数 | 2,162 | 25 |
| WAV 字节 | 62,038,440 | 499,258 |

容量：提取数据 63,246,017 字节；下载源文件 461,683,185 字节；合计 524,929,202 字节（约 0.49 GiB），低于 70 GiB 资产预算。启动前空闲盘约 932 GiB，高于 100 GiB 要求。

## 证据摘要

| 文件 | SHA256 |
| --- | --- |
| `manifest.json` | `c0dec2f28cf4ade22035a14410f62dc26e4b7d869e6e8a3a14f147f367edd711` |
| `dataset.lock.json` | `6ec3fe579a9ff035e1927ca98b16a27f8232acd91e2e2b6984463398b9176c19` |
| `prepare_report.json` | `8ce9836b13bc715642c1c2528a256ea7df782896959729aaf5129fc5fb5b6f53` |
| `prepare_events.jsonl` | `b3c4546aba5ed7dab3dbcad094802ccfb063fbde2b210c1e0cc10b3a44a189a5` |
| `verify.log` | `c0d14ef2c9b8612a85c7bee3d66340a2c609a671ce6e87e75259833cb5c709c9` |
| `source/en_us/test.tsv` | `74c046239374deeb60fa63f258f907388093a32bcaa3140965f70ef05c79f7ca` |
| `source/en_us/dev.tsv` | `9d57ee7e91e9d4c92edb39f6bbea668ef8dc2a3ff96eb510d5580b2ad05d17ec` |
| `audio/test.tar.gz` | `d9c2e37b41aacd41bc283554a0a82b5476b36887049774ecb2819dcaaa55a356` |
| `audio/dev.tar.gz` | `2658fda72f199e12676ecac9415094667a4e14e149b146e568ea00b2a2f0954c` |

音频归档保留在远端 Hugging Face 缓存，WAV 和事件日志不进入 Git。

## 限制

旧远端 manifest 与原始音频已缺失，本轮记录的是新恢复副本的逐文件哈希；数量和总时长与历史一致，但不宣称与原 manifest 逐文件验同。旧日志不存在也不能用于证明删除时间。FLEURS 是朗读语音，本轮没有增加真实发声末端标注；后续 WER 必须复用同一原始参考和 `whisper-normalizer==0.1.12` 口径。
