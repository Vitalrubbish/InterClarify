# `src/interclarify/realtime/`

## 作用

P1.2“实时双工链路”的无头运行时（[engineering_implementation.md](../../../engineering_implementation.md) 第 5.2 节）。它把**未修改**的官方 DuplexCascade 运行时（分离的 Kyutai STT/TTS 服务 + 官方 `server.py` 控制模型）接到脚本化的音源上，代替浏览器完成实时双工验收：系统发声时仍接收用户音频、静音/backchannel/常规回答/用户打断停播/继续倾听，以及连续脚本化场景下的崩溃、队列堆积与音频设备抢占观察。

设计约束：

- 客户端只讲官方浏览器协议（二进制 float32 PCM 帧 + JSON 控制消息），不改服务端一行代码；
- 全链路只有一个播放所有者（`playback`），已播音频不可撤销，`stop` 只取消未播放尾部；
- 面向服务的 pacing 永远是实时（80 ms 帧间隔），时钟只约束本地播放所有者与空闲等待；
- 无音频设备的 headless 环境用虚拟播放 sink + 已播音频落盘取证；本地开发机可换 sounddevice。

## 文件

| 文件 | 说明 |
| --- | --- |
| `clock.py` | [clock.md](clock.md)：real/virtual 节拍时钟 |
| `playback.py` | [playback.md](playback.md)：单一播放所有者（virtual / sounddevice） |
| `scenarios.py` | [scenarios.md](scenarios.md)：脚本化用户音频场景与期望 |
| `client.py` | [client.md](client.md)：无头全双工 WebSocket 客户端 |

配套入口与资产：

- `scripts/run_p1_2_live_link.py`（[run_p1_2_live_link.md](../../../scripts/run_p1_2_live_link.md)）：P1.2 运行入口；
- `scripts/prepare_p1_2_scenarios.py`（[prepare_p1_2_scenarios.md](../../../scripts/prepare_p1_2_scenarios.md)）：用固定 Kyutai TTS 合成场景语音；
- `configs/p1_2_scenarios.json`：场景定义（入库）；音频在 `assets/p1_2_scenarios/`（`*.wav` 不入库）；
- 官方 LLM 服务子进程管理：`src/interclarify/duplex/official_server.py`（[official_server.md](../duplex/official_server.md)）。
