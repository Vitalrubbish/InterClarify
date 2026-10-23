# evaluate_xturnix_control.py

## 作用

执行 XTX-010 的 Listen/start–keep 离线校准，Speak 校准后置。真实模型仅在远端调度 GPU 作业内运行，读取冻结 gzip JSON 输入及来源摘要，复用既有 conda 和 PT 权重；不运行 ASR、TTS 或参数更新。

## 设计与核心方法

模块采用函数，不定义业务类。`verify_model` 按已有模型锁逐文件核对大小和 SHA256，核对固定 revision；`score` 使用官方 pipeline、Listen、FP32 与 2,048 token 合同，记录合法动作分数、输入摘要、移除历史数、token 数、推理时间及失败。标签不进入 pipeline。

`metrics` 将句中判断归并到原话轮，计算默认或指定阈值下的末端召回、任一句中误抢话、无误抢话的末端命中、快照混淆矩阵、完整分母与失败。`choose_threshold` 只接收开发集分数，在全部可区分阈值中按[冻结协议](../../dev/XTurnix/listen_calibration.md)选工作点；并列时优先更低误抢话和更高阈值。

`paired_intervals` 按原会话重采样，给出默认与校准差值的配对 95% 区间。`main` 先验证文件摘要，完成 dev 推理并写出不可覆盖的阈值文件，之后才解压读取 test 输入并推理。输出逐例分数、dev 阈值曲线、冻结工作点、模型/环境/资源及 test 比较。打分错误保留为 null，失败末端计漏接话，句中失败使安全结论不能通过。

`ranking` 另报快照级 ROC-AUC，平分并列分数，只用于观察区分能力；重叠停顿不是独立样本，AUC 不能替代话轮级误抢话预算或部署结论。阈值曲线中的混淆矩阵可复算 PR 曲线。

当观察点没有任何当前词时，不调用模型而保持 Listen，状态为 `abstain_empty_text`、分数 null，不纳入模型混淆矩阵；计划分母保留。阈值选择允许该已冻结 abstain 规则，不允许跳过真正的 dev 推理失败。该规则与 source 标签无关。

## 运行

```bash
python scripts/remote/evaluate_xturnix_control.py \
  --inputs /path/to/frozen-inputs --output /path/to/new-run/results \
  --model /path/to/xturnix-pt --model-lock /path/to/xturnix-pt.lock.json
```

完整输入和分数留远端；Git 保留无正文清单与汇总。原始参考词时间不是 Nemotron 在线到达时间，推理耗时也不称为在线接话延迟。小型契约测试只覆盖未来词边界、会话隔离及话轮归并/阈值选择。
