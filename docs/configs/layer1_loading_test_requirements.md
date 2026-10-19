# 加载验证的HTTP测试依赖

`configs/layer1_loading_test_requirements.txt`固定httpx/httpcore/sniffio，仅补齐独立训练conda中FastAPI TestClient缺少的测试包，无类或方法。既有h11=0.16.0、anyio/certifi/idna已满足依赖，不升级torch/transformers/peft。

克隆环境的pip自身内部导入已知损坏，使用conda base可运行的pip通过`--python <独立训练prefix>/bin/python`管理目标环境，并加`--no-deps`安装这三项；包元数据/版本和测试结果在安装后核验。不修补历史服务环境、不向base安装包。远端HTTP回归通过后仍须GPU零更新和实际服务逐拍对照。
