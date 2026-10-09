# `scripts/remote/download_xtalk_round1_models.py`

## 整体作用

`run_xtalk_round1.py download` 的并行变体：把五个模型的 snapshot 下载并发执行（每模型 8 个文件线程），其余语义与串行版完全一致——首次解析不可变 revision 写入 `models.lock.json`，复用已有锁定，禁止浮动 `main`，下载完成后统一把 snapshot 路径写回锁定文件（单写者，避免并发改锁）。

## 使用方式

```bash
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
conda run -n xtalk-round1-tools python scripts/remote/download_xtalk_round1_models.py \
  <model-root> configs/xtalk_round1.yaml
```

## 背景

- hf-mirror 会把大文件重定向到 Xet CAS 后端并返回 401，因此必须设置 `HF_HUB_DISABLE_XET=1` 走常规 resolve 通道。
- 集群到 hf-mirror 的单连接吞吐有限，串行五模型约 4 小时；按模型并行后实测约 7 MB/s，缩短到约 1 小时。下载可断点续传，杀掉进程重跑即可。
