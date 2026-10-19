# UltraChat 冻结源文件获取

`fetch_layer1_sources.py`只下载004登记的原始UltraChat来源，不做过滤、生成或训练。`main`读取冻结来源清单，按固定revision逐文件下载；`fetch`流式写独立.part，核对发布字节数和LFS SHA256后原子命名，已有文件须重新核验才能复用。失败保留日志，不静默改来源或使用未验真内容。

`--manifest`指定已冻结清单，`--output`指定远端数据目录，`--endpoint`默认官方HuggingFace，可显式使用hf-mirror镜像但revision和内容摘要不变。下载结果保存download_manifest.json，记录URL、字节、SHA256及状态；完成来源下载不表示数据切分、控制监督或训练门禁通过。远端conda CPU作业执行，不占训练GPU。
