# Nemotron EN160 文本表面形式核验

2026-10-19。当前发布 EN160 模型与现役 ASR conda 环境，源码 `07b0d51`。用户授权核对小任务能否直接在调试节点GPU完成；实测 `d6-hpc-debuggpu-001` 的0号2080 Ti成功完成6条合成短音频探针，退出0，加载22.28秒、合计解码8.68秒，采样显存峰值2648MiB。单进程、4CPU、32GiB虚拟地址空间、600秒超时；进程结束后释放GPU。原4090排队作业 `job-179241307868577977613-xuan-zhang` 已撤销，未执行。

`report.json` 保存完整decoder文本/ID更新；`manifest.json` 保存espeak-ng脚本文本、音频路径和摘要，WAV留远端。输入使用整段音频与EOF排空，复用当前原生160ms特征/解码路径；它验证原始转写形式，不模拟真实到达时钟，不估计流式延迟。合成语音识别有错误，以下原样保留。

| 场景 | 当前ASR实际最终输出 |
| --- | --- |
| 英文缩写 | Don't stop. I'll call when we're ready |
| 日期时间 | The meeting is at nine thirty AM on October nineteenth twenty twenty six |
| 时刻 | Versus leave at six thirty and seven thirty |
| 年份 | In two thousand two, the town was destroyed |
| 金额 | The prices forty two dollars and fifty cents |
| 电话数字 | My phone number is five five five one two three four |

缩写中间状态明确出现 `D → Don → Don' → Don't`、`I → I' → I'll`、`we → we' → we're`。因此在线600ms刷新可能遇到词内或缩写内部文本，不能要求合成微轮一律在完整单词边界切分。官方DuplexCascade论文只公开1–7 token随机分拍，未公开作者对缩写的具体保护规则；本项目Qwen tokenizer按 `don`/`'t` 等切分符合token粒度，但不能据此声称精确复刻官方生成器。

对远端已存真实录音轨迹的只读统计：`interclarify-asr-selection/runs/full100-parallel-13a846d/shard-*/repeat-*/nemotron_en-160/sample-*.jsonl` 共200条（100条录音两轮重复），200条含大写、0条含阿拉伯数字、58条含常见英文数词；共5424次字母词内增量。参考年份2002实际输出two thousand two，参考06:30/07:30实际输出six thirty/seven thirty。模型词表含0–9，因此这些观测不能外推为永不输出阿拉伯数字。以首非空时刻起拍、按600ms对已存更新作离线窗口重放，30个撇号缩写/所有格跨度有13个被边界穿过；该离线重放不是新的线上测量。

r4全量计划的只读统计：1500条对话、5655个原用户长轮、82503个有来源用户微轮；534个用户长轮含数字，3432个微轮含数字；4185个撇号缩写/所有格跨度中996个跨拍，2548个数字跨度中894个跨拍。r4没有数字口语化处理，原样和去句读都保留大小写及数字形式，故**当前r4并未实现用户文本与ASR表面形式的一致性**。数据来自UltraChat，无法仅通过字符切分复现实际ASR时钟。

后续数据修订应保留大小写和撇号，允许真实存在的词内增量；针对用户侧数字、日期、时间、金额和电话等按语义生成英文读法，再做共同分拍和增强，保留原文到规范化文本的映射。数值口语化必须区分年份、基数、时刻和逐位号码；assistant保持原正文。不得把所有数值逐位替换或将所有文字统一小写。规则实现与新数据重建另由[021](../../../docs/issue/archive/021_asr_surface_data_revision.md)跟踪。

失败记录：debug-r1缺少`/usr/bin/time`，退出127；debug-r2在16GiB虚拟地址空间上限下CUDA加载失败，退出1，当时显存仍有8.10GiB空余；debug-r3提高到32GiB虚拟地址空间后成功，未改变精度/权重。失败原件保留远端，执行命令在`run_debug_r3.txt`。该内存上限为虚拟地址空间，不是实际常驻主存。

后续状态：021已按上述观测完成用户数值读法转换，正式[r5数据](../../layer1_training/issue004-build-20261019-r5/README.md)全量机器审计通过；r4已删除，用户明确取消r5人工复审，004已关闭。上文r4统计保留为修订前观察记录。
