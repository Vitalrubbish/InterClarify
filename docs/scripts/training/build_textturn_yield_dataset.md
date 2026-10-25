# ASR更新让轮数据构造

`scripts/training/build_textturn_yield_dataset.py`负责TT-010独立版本的轨迹、前缀标注、正式快照和摘要，仅读取旧TT-001中选定的训练／开发来源。完整合同见[版本说明](../../dev/TextTurn/asr_update_yield_dataset.md)。不调用模型、网络或GPU。

`YieldTrace`是唯一模拟输出所有者，管理当前用户轮／版本、历史、输出ID、生成／播放游标、待消费外部事件及决策快照。`step`先更新当前可见事实，再保存快照和动作掩码，最后接受动作。`update`拒绝非追加修订并忽略旧轮、旧版本及重复文本；`user_segment`把手写的可判定语义边界展开为逐前缀标注，边界前保留unknown。这些是有限合成标注，不是运行时词表或普适语义判断。

`accept_start`记录接受和模拟开播；`progress`分开推进生成与播放；`callback`检查finish条件、关闭或记录过期回调；`drain`产生明确模拟的正常播放完成。stop请求后仍记录Speak，80ms模拟停播确认才关闭；正常尾窗为960ms。`validate`校验输出配对及动作损失。open轨迹必须显式标记truncated；error不改写成finish。

`scenario`构造12类对照，包括同刻事件两种顺序及异常退出。`build`检查旧资产摘要、来源组切分，固定抽取24／12来源，保留完整事件和前缀审核表，限制正式集每机会keep／unknown各两个。生成尾窗使用单独类别，保证完成后仍Speak的快照不会被早期keep采样挤掉。所有start／stop保留，超过2048 token则显式排除。

使用已有conda环境、单线程运行，CLI内部限制2GiB地址空间；外部timeout限制总时间：

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false timeout 600 conda run -n interclarify-dev python scripts/training/build_textturn_yield_dataset.py --legacy artifacts/textturn/tt-001-frozen-r3 --output artifacts/textturn/tt-010-yield-v1-r2
```

输出必须为新目录，失败时保留部分证据，不覆盖旧版本。清单记录来源／快照／机会／类别及终态计数、文件摘要和资源上限。大体积逐例资产保存在artifacts，不加入Git；中文报告保存位置及可复核摘要。输入没有未来文字、类别、语义标注或参考完成时间，finish用普通JSON编码且全屏蔽损失，不增加token或修改旧候选。
