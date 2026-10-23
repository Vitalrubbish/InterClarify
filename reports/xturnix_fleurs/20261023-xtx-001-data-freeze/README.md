# XTX-001：FLEURS 输入与历史 ASR 基线冻结

2026-10-23。状态：远端冻结与独立复核完成；本阶段不加载模型、不回放、不计算 WER 或 XTurnix 指标。

## 固定输入

| 项目 | 值 |
| --- | --- |
| 数据集 | `google/fleurs` |
| revision | `70bb2e84b976b7e960aa89f1c648e09c59f894dd` |
| 正式输入 | `en_us/test` 按 `SHA256(filename)` 升序前 100 条 |
| 预热输入 | `en_us/dev` 同规则 1 条 |
| test 首末 | `2074231104398719826.wav`、`1277588711703410007.wav` |
| dev | `786465049904960526.wav` |
| test 总时长 | 969.26 秒 |
| test 标准化词数 | 2,162（`whisper-normalizer==0.1.12`） |
| 音频 | 16 kHz 单声道原始字节；未重采样、未转换声道、未裁剪静音 |

test 与 dev 文件名集合无交集，分别保存在独立目录。100 条正式输入的 WAV 合计 62,038,440 字节；dev 为 499,258 字节。

## 数据来源与复核

已有 2026-10-22 的 FLEURS 数据目录被只读复用；没有读取或信任旧 manifest。脚本从固定 revision 的 TSV 重新执行选样，要求复用目录中的 101 个 WAV 与选择结果完全一致，再复制到新的冻结目录并重新计算全部哈希。

| 复核项 | 结果 |
| --- | --- |
| 独立选择 | test 647 条中取 100，dev 394 条中取 1 |
| WAV 数量 | 101（100 test＋1 dev） |
| SHA256 校验 | 101/101 |
| test/dev 路径与集合 | 无交集、无多余文件 |
| 选择顺序 | 逐例 `SHA256(filename)` 严格升序 |
| 总时长／词数 | 969.26 秒／2,162 词 |
| 历史基线 | 来源、数值与限制逐项核对 |

`verify-data` 退出码为 0，并写入独立复核记录。旧 manifest 已缺失，因此本次是新的逐文件冻结，不宣称与旧 manifest 逐文件验同。

## 历史 ASR 常数

来源为固定提交 `f6ad9d9ba04e4e046dcfcdd480b5343165466046` 的选型报告及重复轮次汇总：

| 指标 | 值 |
| --- | --- |
| 逐词交付 P50 | 413.582852 ms |
| 逐词交付 P95 | 1,032.668798 ms |
| 可测正确且可对齐词 | 3,068 / 4,324（70.95%） |
| WER | 7.68% |

定义为“正确且可对齐词的首次交付时间减去 CTC 估计参考词结束时间”，覆盖全部可测词。该 P50 只作为典型逐词开销常数，不是均值、末词专项实测、整体 P95 或端到端成绩；缺失词不补 0。

## 远端位置与产物

源码为 detached worktree `e337ab8`；数据环境为现有 `~/miniconda3/envs/interclarify-x2-turn-data`（Python 3.11.17，`whisper-normalizer==0.1.12`、`soundfile==0.14.0`、`huggingface_hub==0.36.2`），仅用于哈希与文本标准化。

```text
~/interclarify-xturnix-fleurs/
├── dataset/fleurs_en_us/           # 101 WAV、TSV、manifest、锁、基线与复核记录
├── source/e337ab8/                 # 冻结源码
├── xtx-001-prepare.log
└── xtx-001-verify.log
```

## 证据摘要

| 文件 | SHA256 |
| --- | --- |
| `manifest.json` | `c1677bd6c0bc2375be10f323a8e3d6870448283b4f737bbde61e4eb273052840` |
| `dataset.lock.json` | `3fb2eb15c14ad662eb88080c6508a5c4b3e655d9ec8a6fe5c4f9c11c908c256f` |
| `historical_asr_baseline.json` | `1de45c5542ab4a1bbd1d458d35a3321f10ede0b82c415bc93550198393e9dc2a` |
| `prepare_report.json` | `6474843d3c14f1bf04a5aa10a9a81219e1526b829d193917292688999def290a` |
| `verification.json` | `a2676eff3477c7f5a9d15c2c37877129067819cd7e7cf8cfd5fc49711f838189` |
| `prepare_events.jsonl` | `c180a359ccd51a23485c99e22e757ea26be23822f4f45374aad26790e029c759` |
| `xtx-001-prepare.log` | `8770917c49f4850839ba272eaa07f8d6c2d94c856ed0d5a23415e10286d67fdd` |
| `xtx-001-verify.log` | `6ec568cc4b558b051d2c838b1818cd7510c2e89d40c0335f9712acac8d95f1c3` |

`prepare_report.json` 自报的 manifest／lock／baseline 摘要与上表一致；`verification.json` 记录复核时的 manifest 与 baseline 摘要。

## 资源

复用数据，无模型下载与 GPU。启动前空闲盘约 902 GiB，结束后约 902 GiB；数据目录 63,241,343 字节（报告时点），远低于 10 GiB 资产上限。数据准备耗时 3.75 秒，未接近 1 小时上限。

脚本说明见 [docs/scripts/remote/xturnix_fleurs_test.md](../../../docs/scripts/remote/xturnix_fleurs_test.md)，工作单见 [XTX-001](../../../docs/issue/XTurnix/xtx_001_fleurs_data.md)。
