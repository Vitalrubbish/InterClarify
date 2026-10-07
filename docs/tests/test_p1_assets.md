# `tests/test_p1_assets.py`

## 文件作用

测试 P1.1 服务器资产脚本的本地安全边界，不下载模型也不访问外网。

## 覆盖内容

- `--dry-run` 能从仓库配置解析固定 DuplexCascade 官方提交、Hugging Face revision 和权重文件名；
- 模型目录落在仓库内部时被拒绝，避免把大文件写入 Git 工作树。
