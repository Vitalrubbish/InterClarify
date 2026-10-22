# X2Q-007：历史 FLEURS 子集与远端资产核查

状态：已完成，2026-10-22 归档。

## 请求

用户取消本轮 FDB 测试，要求登录远端确认此前 ASR 选型用过的 FLEURS 子集。此工作单只读核查，不下载数据、不部署模型、不自动执行新测试。

## 结果

已确认历史使用 `google/fleurs` 固定 revision 的 `en_us/test` 哈希选样 100 条、969.26 秒、2,162 个标准化参考词，另有 dev 1 条预热。远端旧 dataset/runs 和默认 HF 缓存路径均不存在；固定 revision 与选样脚本可从 Git 追溯，可据此规划重建。

详细路径、检查范围、恢复注意和适用边界见 [核查记录](../../dev/X2-Turn/fleurs_subset_verification.md)。本轮 FDB 待实施工作单 X2Q-002—006 已按用户取消归档。
