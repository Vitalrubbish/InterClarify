# 音频 I/O 条件报告（P0）

对应 [engineering_implementation.md](../engineering_implementation.md) 第 4.2 节第 5 项。由 [scripts/check_audio_io.py](../../scripts/check_audio_io.py) 生成，目标参数与 `configs/base.yaml` 的 `audio` 段一致。

## 目标参数

| 项 | 值 |
| --- | --- |
| 采样率 | 16000 Hz（X-Talk turn detector 的统一输入起点；具体模型可在适配层重采样） |
| 声道 | 1（单声道） |
| 数据类型 | float32 |
| 块长 | 80 ms = 1280 samples |
| 目标缓冲块 | `suggested_blocksize=1280` |

## 集群与登录节点实测（2026-10-07）

命令：

```bash
python scripts/check_audio_io.py --json-out <证据目录>/audio_io.json
```

结果摘要：

```text
status: NO_DEVICES
sounddevice_available: True
aec_host_api_present: False
default_input: -1
default_output: -1
input_devices: 0
output_devices: 0
note: No OS-level AEC host API detected; plan a software echo-suppression step
```

- 宿主机为无音频外设的 headless 计算节点，PortAudio 已可用但无任何输入/输出设备；`NO_DEVICES` 属预期，不作为失败。
- 未检测到操作系统级回声消除（Windows WASAPI 之外无内建 AEC）。

## 结论与 local profile 要求

1. 真实麦克风/扬声器验证需在带音频设备的开发机上，使用 `configs/local.yaml`（`input_device=default`、`output_device=default`、`clock.mode=real`）执行本脚本，应得到 `status=OK` 并列出设备。
2. 无 OS AEC，按 [engineering_implementation.md](../engineering_implementation.md) 的控制边界，本地交互需要额外选择其一：
   - 软件回声抑制/半双工（push-to-interrupt）作为 P1 的临时方案；
   - 或使用耳机隔离扬声器回声。
   具体方案在 P1 X-Talk 实时链路验证时固定并记录，`configs/local.yaml` 的 `audio.echo_cancellation` 届时置为实际值。
3. 集群侧不采集真实音频，音频以文件/回放方式驱动，因此无设备不阻塞 P1 的功能差距审计。
