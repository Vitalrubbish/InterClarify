# `src/interclarify/realtime/clock.py`

## 作用

P1.2 双工 harness 的节拍时钟。两种实现：

- `RealClock`：墙上时钟（`time.monotonic` / `time.sleep`）。实时运行的播放所有者按真实时间推进播放头，因此“系统发声期间仍收到用户音频”等双工证据是按真实重叠测得的。
- `VirtualClock`：从 `origin`（默认 0）出发的手工推进时钟，`sleep` 立即快进虚拟时间并返回，用于 CPU-only 的控制路径快速检查（如单元测试），另提供 `advance(seconds)` 显式推进。

`make_clock(mode)` 按配置 `clock.mode`（`real`/`virtual`）构造。

## 关键约束

- **面向服务的 pacing 永远是实时**：官方服务端把麦克风流当 24 kHz 实时流消费，所以客户端无论在哪种时钟模式下都按真实 80 ms 间隔发送音频帧；时钟只约束本地播放所有者与空闲等待（对应工程文档第 5.4 节“预录音频 + 虚拟播放时钟”的降级路径）。
- 虚拟时钟下 `frames_sent_while_speaking` 会失真（播放被瞬间抽干），双工证据应在 `clock.mode=real` 的运行中采集（集群 profile 即 real）。
