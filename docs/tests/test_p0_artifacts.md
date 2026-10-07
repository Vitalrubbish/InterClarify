# `tests/test_p0_artifacts.py`

## 作用

P0 交付物的单元与集成测试，覆盖配置合并、清单确定性与冒烟日志的结构一致性。

## 用例

- `ConfigTest`：
  - profile 在 base 之上正确合并，未覆盖的 base 值保留；
  - 未知 profile 抛 `ValueError`；
  - 配置指纹稳定且随 profile 变化；
  - `${VAR:-default}` 环境展开；
  - 路径解析与 `resolved_config.yaml` 往返写入。
- `ManifestTest`：
  - `manifest_fingerprint` 忽略 `run_id`、时间、输出目录等易变字段；
  - Git 提交被记录且为 40 位十六进制。
- `SmokeTest`：
  - 通过子进程运行两次 `run_p0_smoke.py`，断言事件类型序列相同、`metrics.json` 相同、`manifest.json` 关键字段正确。

## 运行

```bash
conda run -n interclarify-dev python -m pytest -q
```

测试不依赖 torch/CUDA，仅需 numpy、PyYAML 与项目源码路径。
