# Issue 040：延后启动候选 FDB 测试提交

用户要求查看训练并提交测试，工作单元为 [040c](../../../docs/issue/archive/040c_delayed_start_fdb_test.md)。040训练及干净进程候选核验退出0，完整1235步/2469序列/1000条；最新数据和加权目标已核验，112个LoRA更新且冻结参数不变。[训练证据](../issue040-delayed-training-20261020/README.md)已保存。

测试只引用最终checkpoint，SHA256为 `266a37a28699d0c3f36b6a6305374bc89a1a2ff2af7a37fd1eb4caf1ad915346`，候选 `T2_R3_delayed_start`。新增`delayed_t2`入口只改变条件选择和训练预检；实际训练资产已通过本次预检，所有嵌入Python段及shell语法通过检查。测试服务仍再次完整恢复候选和复现生成。

沿用037同一25个历史FDB输入、70份音频/标注资产、134文件X-Talk冻结快照、Nemotron EN160、Kokoro af_heart、600ms、BF16/64-token贪心及5秒诊断尾窗，官方WAV仍与原输入等长。驱动、ASR/TTS和播放逻辑不改。旧两轮T2只读作开发回归对照，本次不将历史子集称为未见泛化测试。

预算2×4090/16CPU/64GiB、一个并发作业、最长4小时，输出10GiB、空闲盘保留15GiB；只读引用训练资产，不复制权重或删除旧结果。提交前无运行作业，空闲盘约595GiB。

提交后记录作业ID、冻结源码和资源；未完成测试前不填写效果改善、官方评分或人工内容验收通过。评价包括接话、插话后新响应、暂停误抢/附和误停、文字拍提前finish、finish无正文、协议错误与时延，原窗口和诊断尾窗分开保留失败及静默。

调度器已接受测试作业 `job-179250639360566170646-xuan-zhang`，最终状态 **Completed/退出0**，冻结源码 `94b05f838815259439eb0c0335d14f58f85a0e3a`，run_id `issue040-delayed-fdb-r1`。精确路径及资源原始调度文件已按精简要求删除。25个会话均完成，无缺失、失败或协议错误。

启动预检已通过：训练最终资产、25会话/70份输入、134个X-Talk源码文件及两张4090均核验成功，4组候选/加载/服务/驱动回归完成，ASR/TTS健康检查为ok。原始startup记录已按精简要求删除。测试模型服务已再次完成候选完整权重与生成IDs复现，最终25会话执行通过。

## 结果与阶段关闭

正式报告见[Layer 1训练与FDB阶段报告（历史版本）](https://github.com/Vitalrubbish/InterClarify/blob/717fcf037d471d07be41172b5b69b0dd404cfcb6/docs/layer1_training_fdb_report.md)。自然接话新回复播放由第二轮1/5增至3/5，合成插话后由4/5增至5/5；仍有漏答、提前播放、无finish正文启动及延迟增加。39次finish均在无新增文字拍，文字拍finish与finish无正文均为0。合成暂停新增出声中的4例仅在诊断尾窗，不计作原窗内抢话。

逐例证据见[results.json](completed/results.json)、[时间线审计](completed/timing_audit.json)、[启动控制](completed/response_start_controls.json)、[执行验证](completed/validation.json)和[25例CSV](test_samples.csv)。用户明确接受当前话轮控制误差，要求停止继续训练并关闭相关Issue。阶段决定为stop training / close current stage，见[关闭记录](closure.json)；官方评分、完整FDB与全面人工音频复核未执行，不补写为通过。
