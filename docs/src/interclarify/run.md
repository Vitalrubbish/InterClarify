# `src/interclarify/run.py`

## 作用

P0 的最小运行上下文，落实实验输出目录规范（[engineering_implementation.md](../../engineering_implementation.md) 第 12 节）。它把一次运行所需的产物集中到一个目录，并提供一个结构化的运行日志。

> 注意：这里的日志只记录**运行生命周期**事件（`run_start`、`run_end` 等）。P1.3 的运行时 `EventRecorder`（记录 ASR/LLM/TTS/播放事件）将复用同一磁盘格式，但属于后续阶段实现。

## 运行目录内容

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | `RunManifest` |
| `resolved_config.yaml` | 实际生效的完整配置 |
| `environment.txt` | 主机/解释器/依赖/加速器快照 |
| `events.jsonl` | 追加式结构化事件，每行含 `seq`、`monotonic_ms`、`wall_time`、`event_type`、可选 `payload` |
| `metrics.json` | 调用方写入的汇总指标 |

## 主要类与方法

- `RunContext.create(output_root, profile, config_dir, overrides, repo_root, run_id, tags)`：加载配置、解析路径、创建运行目录，写入清单/配置/环境文件，并记录 `run_start`；若 `run_id` 对应的目录已存在且非空则抛 `FileExistsError`，避免两次运行混入同一目录。
- `RunContext.record(event_type, **payload)`：追加一条事件并 flush，返回事件字典。
- `RunContext.write_metrics(metrics)` / `finalize(metrics)`：写指标、收尾时间、更新清单并记录 `run_end`。
- `close()` 与上下文管理器支持。

## 关键约束

- 事件带单调时钟（`monotonic_ms`）与墙上时钟（`wall_time`）两种时间，便于离线回放按虚拟时钟重放；
- `run_id` 必须唯一：`events.jsonl` 以写模式（`w`）新建，`create` 拒绝复用非空运行目录，因此不会出现追加旧日志、重复 `run_start` 或重复序号；
- `output_root` 默认取配置 `run.output_root`（相对仓库根目录），目前为 `experiments/`；该目录属于运行产物并由 `.gitignore` 忽略，避免冒烟或实验运行改变代码工作树状态；
- 不涉及模型推理；P0 冒烟脚本（`scripts/run_p0_smoke.py`）是其唯一使用者。
