# 英文组件 conda 环境

脚本没有类，以 ENGLISH_COMPONENT_ROOT 下独立 asr/tts prefix 克隆已测环境，绝不修改种子；分别保存 pip freeze 和 conda explicit，然后核验原生 RNNT 与 Kokoro 导入。已有目标环境只核验和导出，不静默升级。种子路径可通过 ENGLISH_ASR_SEED/ENGLISH_TTS_SEED 覆盖；实际版本以运行导出为准。
