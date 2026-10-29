# SharedContext 契约测试

对应 `tests/test_shared_context.py`，使用既有本地 conda，不加载模型。四个场景检查正文词内修订与独立消费者、原子回滚与重复冲突、关闭及过期游标、patch和状态来源引用。断言依赖先于状态、较晚修订不改既有依据；重同步不伪造历史状态。

同时检查历史读取不能使用未来尚未提交的事件水位，释放已关闭话轮后不保留无用的producer计数。

运行：`python -m unittest discover -s tests -p 'test_shared_context.py' -v`。结果证明内存接口合同，不证明 ASR 或控制器质量。
