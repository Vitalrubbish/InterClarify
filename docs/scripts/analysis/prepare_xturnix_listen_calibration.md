# prepare_xturnix_listen_calibration.py

## 作用

从固定版本 LiveKit EoT Bench 的 400 条英文话轮元数据准备 Listen 校准输入，不下载音频或运行模型。对应[冻结协议](../../dev/XTurnix/listen_calibration.md)，输出到独立、不可覆盖的本地目录。

## 设计与方法

模块不定义业务类。`fetch_rows` 顺序读取数据服务分页，核对数量、记录 ID、截断标记及音频引用中的固定 revision，删除音频 URL 后保存元数据与哈希。每次读取≤8 MiB，总正文≤32 MiB，超时 30 秒，无并行下载；不安装依赖。

`make_events` 按原会话哈希分组，只提取每个停顿开始后 100ms 已结束的词作为当前前缀，末次停顿标签 start，其余 keep；标签、时间和分组只留元数据。来源历史先剔除空内容、合并连续同角色消息、移除独立的开场 assistant，以便官方截断规则处理完整 user/assistant 历史对；记录改动，不伪造 assistant 正文。异常与空观察记录为失败候选。

`main` 写出 `dev.json.gz`、`test.json.gz`、不含正文的 `manifest.json`、准备结果及源请求摘要；两个已阅格式检查会话先排除，同源会话不会跨集合。准备输出在模型打分前冻结。输入摘要用于远端验证，原始正文留在忽略目录，不提交 Git。

可通过 `--source-cache` 复用此前准备目录中的源元数据，先核对其来源 revision 和 SHA256，再重新派生输入；原请求摘要保留，并标明本次没有重新下载。这样可以在模型打分前修正准备逻辑，而不重复读取来源。

## 使用

```bash
conda run --no-capture-output -n interclarify-dev python scripts/analysis/prepare_xturnix_listen_calibration.py \
  --output artifacts/xturnix_listen_calibration/20261023-listen-r1
```
