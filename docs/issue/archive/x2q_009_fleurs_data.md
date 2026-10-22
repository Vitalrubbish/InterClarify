# X2Q-009：恢复并冻结 FLEURS 英文子集

状态：已完成并归档（2026-10-22）。依赖：[X2Q-008](x2q_008_complete_protocol.md) 已完成。依据：[测试计划](../../dev/X2-Turn/complete_test_on_fleurs.md)、[历史数据核查](../../dev/X2-Turn/fleurs_subset_verification.md)。

## 目标与工作内容

恢复此前 ASR 选型使用的同一批录音，作为本轮统一输入。

- 固定 `google/fleurs` revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，不得缺省解析最新版本。
- `en_us/test` 按音频文件名 SHA256 升序取前 100 条，`en_us/dev` 同规则取 1 条，预热不计分。
- manifest 保留原始参考、数据集标准化参考、音频 SHA256、声道、采样率、帧数和时长。
- 保留头尾静音，必要的重采样/声道处理记录参数，不增加人工语音末端标注。
- 核对历史总时长 969.26 秒、标准化参考 2,162 词。词数使用固定 `whisper-normalizer==0.1.12` 核对；不一致时先定位原因，不混入其他版本补足。

## 交付

拟在 `scripts/remote/x2_turn_complete_test.py` 提供数据准备入口，同步 `docs/scripts/remote/x2_turn_complete_test.md`，解释整体功能、数据构建类/函数和核心方法。远端保存数据锁、manifest、下载/提取记录和容量统计，Git 不收音频。

## 验收

- [x] 100 test 与 1 dev 无混用，每份文件存在、摘要可核对，参考与音频对应。
- [x] 例数、时长和标准化词数完成核对；没有旧 manifest 时不宣称旧哈希逐文件验同。
- [x] 远端 conda，下载最多 4 CPU、16 GiB RAM、并发 2；整轮资产≤70 GiB、启动空闲盘≥100 GiB。

## 完成记录

2026-10-22 已在远端 `~/interclarify-x2-turn-complete/dataset/fleurs_en_us` 恢复 100 test + 1 dev。独立 conda 为 `~/miniconda3/envs/interclarify-x2-turn-data`，固定 `whisper-normalizer==0.1.12`；下载入口为 `https://hf-mirror.com`，revision 仍固定。`verify-data` 逐文件核对 101 个 WAV 的 SHA256、声道、采样率、帧数、时长和标准化词数，test 总时长 969.26 秒、标准化参考 2,162 词。数据目录 63,246,017 字节，下载源文件 461,683,185 字节，合计约 0.49 GiB；启动空闲盘约 932 GiB。旧 manifest 缺失，未宣称逐文件哈希验同。

实现与说明：`scripts/remote/x2_turn_complete_test.py`、`docs/scripts/remote/x2_turn_complete_test.md`；证据摘要见 [报告](../../../reports/x2_turn_complete/20261022-fleurs-subset/README.md)。本单只恢复输入，不运行候选模型或评定 WER。
