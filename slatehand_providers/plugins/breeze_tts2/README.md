# Breeze TTS 2 Provider

该插件接入用户已部署的 Breeze-TTS-2 HTTP streaming API。Voice Design 使用
Voice Description；Voice Clone / Voice Direction 使用项目内参考音频、完整
reference transcript 和可选 Performance Instruction。Provider 将流式 PCM
在运行时目录中封装为 WAV，Core 再按普通 Generation/Asset 生命周期导入，
不把 WSL 路径写入项目状态。

实例设置只有「运行节点」（本地 Windows / Colab G4，见 `../nodes.py`）：切换只影响新提交，运行中的
任务按句柄回到提交时的节点。
