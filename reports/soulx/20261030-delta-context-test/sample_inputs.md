# 逐样本输入与全部正文变化

由原始 source 与实际 snapshots 交叉核对。时间为已处理真实音频截止；generation 为内部 controller 片段编号。

“最新草稿”可能在同一步被整段结果替换，尚未单独写入 Context；“此前 Context”才是覆盖前实际可读输入。

整段识别按原生 controller 片段触发，内部 reset 不结束逻辑话轮；无在线整段识别时不补造结果。

## original_full

最后一次 asr_delta 草稿：In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I I I I

关闭时实际 Context：In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I I I I

未发生整段重识别。

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |
| 1.240 | 0 | delta | In many cases |
| 1.400 | 1 | delta | In many cases I |
| 1.560 | 2 | delta | In many cases I I |
| 2.200 | 3 | delta | In many cases I I Gap your |
| 3.480 | 4 | delta | In many cases I I Gap your The hours abroad can actually |
| 4.920 | 5 | delta | In many cases I I Gap your The hours abroad can actually P chances |
| 5.080 | 6 | delta | In many cases I I Gap your The hours abroad can actually P chances I |
| 5.240 | 7 | delta | In many cases I I Gap your The hours abroad can actually P chances I I |
| 5.560 | 8 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher |
| 6.200 | 9 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education |
| 6.520 | 10 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back |
| 6.680 | 11 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here |
| 6.840 | 12 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I |
| 7.000 | 13 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I I |
| 7.160 | 14 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I I I |
| 7.480 | 15 | delta | In many cases I I Gap your The hours abroad can actually P chances I I The higher For education The back I here I I I I |

## calibrated_full

最后一次 asr_delta 草稿：In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country.

关闭时实际 Context：In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country.

### 整段识别 1（online，片段 0）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | And many cases the rolling on a gap year of connection actually improve your chance |
| 此前实际 Context | And many cases the rolling on a gap year of connection actually improve your chance |
| 本片段整段识别 | In many cases, enrolling on a gap year course abroad can actually improve your chances. |
| 覆盖后实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. |

### 整段识别 2（online，片段 1）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 此前实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 本片段整段识别 | I moving into higher education back in your home country. |
| 覆盖后实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. |

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |
| 0.440 | 0 | delta | And |
| 0.600 | 0 | delta | And many |
| 0.920 | 0 | delta | And many cases |
| 1.080 | 0 | delta | And many cases the |
| 1.400 | 0 | delta | And many cases the rolling |
| 1.560 | 0 | delta | And many cases the rolling on a |
| 1.880 | 0 | delta | And many cases the rolling on a cap |
| 2.040 | 0 | delta | And many cases the rolling on a gap year |
| 2.680 | 0 | delta | And many cases the rolling on a gap year of |
| 3.160 | 0 | delta | And many cases the rolling on a gap year of connection |
| 3.480 | 0 | delta | And many cases the rolling on a gap year of connection actually improve |
| 3.800 | 0 | delta | And many cases the rolling on a gap year of connection actually improve your |
| 3.960 | 0 | delta | And many cases the rolling on a gap year of connection actually improve your chance |
| 4.440 | 0 | turn | In many cases, enrolling on a gap year course abroad can actually improve your chances. |
| 5.240 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the |
| 5.560 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the a higher |
| 5.720 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher |
| 6.200 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education |
| 6.360 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by |
| 6.680 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your |
| 6.840 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home |
| 7.320 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 7.480 | 1 | turn | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. |

## calibrated_prefix

最后一次 asr_delta 草稿：And many cases the rolling on a gap year of connection

关闭时实际 Context：And many cases the rolling on a gap year of connection

未发生整段重识别。

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |
| 0.440 | 0 | delta | And |
| 0.600 | 0 | delta | And many |
| 0.920 | 0 | delta | And many cases |
| 1.080 | 0 | delta | And many cases the |
| 1.400 | 0 | delta | And many cases the rolling |
| 1.560 | 0 | delta | And many cases the rolling on a |
| 1.880 | 0 | delta | And many cases the rolling on a cap |
| 2.040 | 0 | delta | And many cases the rolling on a gap year |
| 2.680 | 0 | delta | And many cases the rolling on a gap year of |
| 3.160 | 0 | delta | And many cases the rolling on a gap year of connection |

## calibrated_repeat

最后一次 asr_delta 草稿：In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. I

关闭时实际 Context：In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. I

### 整段识别 1（online，片段 0）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | And many cases the rolling on a gap year of connection actually improve your chance |
| 此前实际 Context | And many cases the rolling on a gap year of connection actually improve your chance |
| 本片段整段识别 | In many cases, enrolling on a gap year course abroad can actually improve your chances. |
| 覆盖后实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. |

### 整段识别 2（online，片段 1）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 此前实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 本片段整段识别 | I moving into higher education back in your home country. |
| 覆盖后实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. |

### 整段识别 3（online，片段 2）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education back in your home country |
| 此前实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education back in your home country |
| 本片段整段识别 | In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. |
| 覆盖后实际 Context | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. |

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |
| 0.440 | 0 | delta | And |
| 0.600 | 0 | delta | And many |
| 0.920 | 0 | delta | And many cases |
| 1.080 | 0 | delta | And many cases the |
| 1.400 | 0 | delta | And many cases the rolling |
| 1.560 | 0 | delta | And many cases the rolling on a |
| 1.880 | 0 | delta | And many cases the rolling on a cap |
| 2.040 | 0 | delta | And many cases the rolling on a gap year |
| 2.680 | 0 | delta | And many cases the rolling on a gap year of |
| 3.160 | 0 | delta | And many cases the rolling on a gap year of connection |
| 3.480 | 0 | delta | And many cases the rolling on a gap year of connection actually improve |
| 3.800 | 0 | delta | And many cases the rolling on a gap year of connection actually improve your |
| 3.960 | 0 | delta | And many cases the rolling on a gap year of connection actually improve your chance |
| 4.440 | 0 | turn | In many cases, enrolling on a gap year course abroad can actually improve your chances. |
| 5.240 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the |
| 5.560 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the a higher |
| 5.720 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher |
| 6.200 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education |
| 6.360 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by |
| 6.680 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your |
| 6.840 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home |
| 7.320 | 1 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving the higher education by in your home country |
| 7.480 | 1 | turn | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. |
| 8.120 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. The and |
| 8.280 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many |
| 8.600 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases |
| 9.400 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a |
| 9.720 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a gap |
| 9.880 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year |
| 10.360 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year of |
| 10.520 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year |
| 10.840 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can |
| 11.160 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually |
| 11.480 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve |
| 11.640 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your |
| 11.960 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chance |
| 12.120 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances |
| 12.760 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances and |
| 12.920 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving |
| 13.240 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into |
| 13.400 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher |
| 14.040 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education |
| 14.360 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education backing |
| 14.520 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education back in your home |
| 15.000 | 2 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. And many cases I rolling on a cap year abroad can actually improve your chances of moving into higher education back in your home country |
| 15.160 | 2 | turn | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. |
| 15.320 | 3 | delta | In many cases, enrolling on a gap year course abroad can actually improve your chances. I moving into higher education back in your home country. In many cases, enrolling on a gap year course abroad can actually improve your chances of moving into higher education back in your home country. I |

## silence

最后一次 asr_delta 草稿：（空）

关闭时实际 Context：（空）

未发生整段重识别。

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |

## sensevoice_english

最后一次 asr_delta 草稿：The tribal chieftain called for the boy and presented him with 50.

关闭时实际 Context：The tribal chieftain called for the boy and presented him with 50.

### 整段识别 1（online，片段 0）

| 项目 | 输入文字 |
| --- | --- |
| 最新 asr_delta 草稿 | The drive chief him for the boy and presented him the |
| 此前实际 Context | The drive chief him for the boy and presented him the |
| 本片段整段识别 | The tribal chieftain called for the boy and presented him with 50. |
| 覆盖后实际 Context | The tribal chieftain called for the boy and presented him with 50. |

### 全部在线 Context 正文变化

| 音频截止（秒） | 片段 | 来源 | 当前完整输入 |
| ---: | ---: | --- | --- |
| 1.560 | 0 | delta | The drive |
| 2.040 | 0 | delta | The drive chief |
| 2.360 | 0 | delta | The drive chief him |
| 3.000 | 0 | delta | The drive chief him for |
| 3.160 | 0 | delta | The drive chief him for the |
| 3.480 | 0 | delta | The drive chief him for the boy |
| 4.120 | 0 | delta | The drive chief him for the boy and |
| 4.280 | 0 | delta | The drive chief him for the boy and present |
| 4.440 | 0 | delta | The drive chief him for the boy and presented |
| 4.760 | 0 | delta | The drive chief him for the boy and presented him |
| 4.920 | 0 | delta | The drive chief him for the boy and presented him with |
| 5.080 | 0 | delta | The drive chief him for the boy and presented him the |
| 6.840 | 0 | turn | The tribal chieftain called for the boy and presented him with 50. |
