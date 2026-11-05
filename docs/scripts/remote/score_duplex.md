# score_duplex.py

## 功能与来源

从 TurnControlComparison 的 `scripts/remote/score_duplex.py` 复用，用于 FDB30 半双工完整系统评测。原文件 SHA256 为 `f8ee91877d05fc84956ba44065ba99df99629958fe7046134c0c79596fa4f38c`。冻结副本随本项目提交，不依赖远端旧运行目录。

## 类与核心方法

无业务类。`align` 使用冻结 Parakeet 产生词时间戳；`scoring_view` 在 ASR 前截到原输入时长；`validate_recording` 核对录音与逐帧证据；`behavior` 实现 TOR 和延迟；`compare_official` 与 `compare_interruption_official` 分别核对冻结官方函数及打断指标代码块。旧 `score_run` 与 `main` 为原完整比较项目入口，本项目使用新的 FDB30 适配入口，不将固定 30 条当作全量 benchmark。
