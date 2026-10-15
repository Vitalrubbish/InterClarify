# `scripts/remote/create_duplex_source_manifest.py`

为 A4 同步包生成源码清单。`tracked_files` 选择配置、远端脚本、根仓库测试与 X-Talk 源码/测试；`build_manifest` 对排序后的文件内容计算 SHA256，再计算整体 snapshot，并记录两个仓库实际 HEAD 和 dirty 状态。`git_value` 允许无 `.git` 的快照目录，但开发机源清单应保留完整来源。脚本没有自定义类。

```bash
conda run -n paratalker-dev python scripts/remote/create_duplex_source_manifest.py \
  --root /absolute/source/tree --output /absolute/source/tree/source_manifest.json
```

生成后同步完整目录和清单；服务器节点只校验该清单。未提交补丁由内容摘要识别，不能将其归入 HEAD 提交。生成文件属于运行资产，不提交 Git。
Manifest 同时覆盖 X2 服务与对照配置，X-Talk 客户端由既有递归源码选择覆盖。
