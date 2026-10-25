# 160ms数据独立核查

`scripts/analysis/audit_textturn_duplex_dataset.py`读取冻结资产逐项验收TT-010重建数据，不运行模型或训练。入口接受`--data`及`--legacy`，调用Hugging Face离线tokenizer核对实际prompt编码，全部检查失败即退出，不改冻结manifest。

脚本没有独立业务类。来源与摘要核查确认TT-001旧文件未变、train/dev沿用原组且不与test重叠。事件核查逐条检查单调时钟、停顿仅发生在非末尾块、暂停长度及控制拍数；独立重算可用附和抽样机会，并检查每次附和都独立关闭。快照核查把每个输入与实际控制请求、当时用户前缀对齐，检查句读归一化、合法动作、单动作损失、finish输入ID和掩码、来源句式配比与首个非附和stop。审核元数据不得混入模型输入。

`begin`和`interrupt`只生成诊断边界样例：多次start/stop及正常finish穿插、完成先于同刻用户更新、打断先于迟到finish、重复及旧轮输入、播放错误、截断。这六条写入boundary_cases.json，不混入正式训练／开发分母；不将异常伪造成正常完成。audit.json保存核查结论和案例摘要，两者均是manifest外的附加证据。

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 timeout 180 conda run -n interclarify-dev python scripts/analysis/audit_textturn_duplex_dataset.py --data artifacts/textturn/tt-010-duplex160-r2 --legacy artifacts/textturn/tt-001-frozen-r3
```

临时概率0用于确定性诊断，不修改正式0.20／0.01配置；模型质量和真实时延仍需另行授权的远端评估。
