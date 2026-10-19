# UltraChat 冻结源文件获取

`fetch_layer1_sources.py`只下载004登记的原始UltraChat来源，不做过滤、生成或训练。`main`读取冻结来源清单，按固定revision逐文件下载；`fetch`流式写独立.part，核对发布字节数和LFS SHA256后原子命名，已有文件须重新核验才能复用。失败保留日志，不静默改来源或使用未验真内容。

`--manifest`指定已冻结清单，`--output`指定远端数据目录，`--endpoint`默认官方HuggingFace，可显式使用hf-mirror镜像但revision和内容摘要不变。`--attempts`默认每文件最多4次请求，`--retry-delay`默认5秒；断流/超时保留.part并按实际字节发Range，续传前重新散列已有partial。206必须有准确Content-Range；服务器返回200时清空当前partial重下，防止追加重复内容。最终大小/SHA256不符、错误范围或超长响应立即拒收，已有正式文件也须复核。重试耗尽失败退出，不把partial登记为完整文件。

下载结果保存download_manifest.json，记录URL、字节、SHA256及状态；完成来源下载不表示数据切分、控制监督或训练门禁通过。远端conda CPU作业执行，不占训练GPU。
