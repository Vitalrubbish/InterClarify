# SoulX-Duplug 官方源码子模块

`third_party/soulx-duplug`是从`https://github.com/Soul-AILab/SoulX-Duplug.git`克隆的Git子模块，作为本地可浏览、可审查的官方实现入口，不复制为自写模型。子模块不包含本项目新增类；模型与原生推理类以内部`model/model.py`的`State_Prediction_Model`和`service/model.py`的`TurnModel`为准，`infer()`组织音频、教师文本与状态，`_asr()`执行门控与窗口修订，`_state_predict()`执行状态前向与规则。

父仓库以gitlink固定实际提交。初次获取可执行`git submodule update --init third_party/soulx-duplug`，或clone父仓库时加`--recurse-submodules`。不在子模块内静默打补丁；若以后改造，应保留明确diff、独立工作单及对应文档。当前克隆只引入源码，不安装依赖、不下载模型、不执行推理；模型和conda按远端独立目录复用。

2026-11-02核对官方 main 为 `a0b9063843df69619b087b95b74597b2176910b8`。本项目只调用官方原生推理入口，不引入外部加载器或替换内部 ASR 的封装。

远端源码位置为 `~/parathink-soulx-duplug/upstream/soulx-duplug`，是独立 Git checkout，对应本地子模块。模型与环境由既有公共路径提供。
