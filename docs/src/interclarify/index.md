# `src/interclarify/__init__.py`

## 作用

`interclarify` 包的入口。P0 阶段只导出工程准备层：配置、运行清单与最小运行上下文。Layer 0/1/2 的运行时模块在 P1 以后加入。

## 核心内容

- 从 `config` 导出 `load_config`、`config_digest`、`write_resolved_config`；
- 从 `manifest` 导出 `RunManifest`、`build_manifest`、`new_run_id`；
- 从 `run` 导出 `RunContext`；
- 定义 `__version__ = "0.1.0"`。

`__all__` 只包含上述公开符号，避免调用方依赖尚未稳定的内部实现。

## 约束

本模块不导入 torch 等重型依赖，保证在纯 CPU 环境也能导入 `interclarify` 以加载配置和清单。
