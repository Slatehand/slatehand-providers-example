# SeedVR2 7B Sharp FP8 Provider

模型级视频超分插件，标识为 `seedvr2.7b-sharp-fp8`。Core 按 `source_video` 和 `seed` 角色构造 recipe；插件不知道模型目录、CUDA 或部署系统。

全局插件设置 `resolution` 选择目标档位：`720p`（短边 720）或 `1080p`（短边 1080，默认）。长边上限固定放宽到 2560，
只防异常画幅，常规 16:9 / 9:16 / 2:1 的放大结果不被截断；最终装配再统一缩放裁切到交付画布。
recipe 的 `input_check` 从 MP4 `tkhd` 读出原视频宽高，短边已达到目标档位的 90% 时在提交前拒绝并提示无需超分
（例如 H3 720p 档的 1280×704 不能再超到 720p）；读不出尺寸时交给模型服务处理。

超分结果保留原视频音轨：H3 生成的对白与音效会被模型服务原样封装回超分视频，Scene 成片照常混入。
SeedVR2 只接受 32 位无符号 seed，manifest 声明 `seed_field(maximum=2**32 - 1)`；Core 以 Segment ID 前 16 位按该上限取模作为首次 seed，之后每次提交递增。


`manifest.py` 声明槽位与参数，`plugin.py` 提供安装工厂。实现通过 `submit_recipe` 接收 Core 校验后的通用请求，再翻译为本插件 HTTP DTO。
