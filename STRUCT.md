# 目录与文件职责

## 根目录

- `AGENTS.md`：协作说明、边界与工程门禁。
- `README.md`：组成、工作区与安装、启动方式、本机部署配置与随 Core 启停的服务。
- `STRUCT.md`：本文。
- `LICENSE`：Apache License 2.0；`THIRD_PARTY_NOTICES.md`：随插件发布的第三方材料与许可证。
- `slatehand-provider.toml`：Core 经 `--provider-dir` 读取的清单（bundle 名、工厂、import 路径、额外依赖）。
- `pyproject.toml`：分发信息、插件 Skill 的 package-data、`services` 可选依赖、ruff 与 pytest 配置。
- `provider.local.env.example`：本机部署配置模板；实际配置 `provider.local.env` 与 `var/` 被 Git 忽略。

## slatehand_providers/ — Core 侧插件、bundle 与部署服务

- `bundle.py`：`example` bundle：按部署配置安装 Mac、whisper.cpp 与 Windows 节点上的插件，并组装随 Core 启停的服务。
- `deployment.py`：读取 `provider.local.env`（未知键拒绝、进程环境优先）与 `var/secrets/` 中的 Windows Token。
- `services.py`：随 Core 启停的服务：Mac LaunchAgent 与本机 whisper-server。
- `colab_tunnel.py`：Colab 模型节点隧道（bundle 服务）：会话在线时经 `colab ssh` 把本机回环端口转发到 VM 模型服务，断开自动重连。
- `plugins/`：具体模型插件，只 import Provider SDK。每个插件子目录都有 `README.md`（用法与契约）、`provider.py`（请求翻译与 submit/observe/cancel/read_artifact）
  和导出用 `__init__.py`；可绑定的插件另有 `manifest.py`（recipe、槽位、参数、设置）与 `plugin.py`（`plugin_instance` 安装工厂）：
  - `agy_image/`：AGY 图片生成/编辑。
  - `codex_image/`：Codex 图片生成/编辑；`prompt_lint.py` 返回格式软提示，`skills/codex-image-prompt-writing/` 随包交付模型写作规范。
  - `nodes.py`：多节点插件共用的路由（设置 `node` 选择新提交的节点，异步句柄保留提交节点）。
  - `breeze_tts2/`：Breeze TTS 2 音色设计与克隆/导演。
  - `indextts2/`：IndexTTS2.5 参考音色克隆，语速与八维情感由 manifest 声明。
  - `whisper_asr/`：whisper.cpp 参考音频转写。
  - `qwen_image/`：Qwen Image 2.1（NoctQ V4）备选生图/改图，`skills/qwen-image-prompt-writing/` 随插件发布（含官方提示词模板）。
  - `minimax_h3/`：MiniMax H3 插件；`manifest.py`、`plugin.py`、`requests.py`、`contracts.py`、`render.py`，以及 `fl2va/`、`ref2va/` HTTP 实现。
    `submissions.py` 为 Colab 节点提供持久提交发件箱：先返回句柄，观察时上传冻结请求，按固定标识查询与幂等重放。
    `prompt_contract.py`、`prompt_codec.py`、`prompt_payload.py`、`prompt_context.py` 负责插件专业格式（`context.shots` 按 Segment 覆盖顺序写入段内切镜软约束），`skills/h3-prompt-writing/` 随插件发布，经 `prompt_skills` 由 `video_prompt` 契约交付。`prompt_lint.py` 是插件的 `prompt_linter`，按官方结构检查对白唯一位置、对白标签、说话者、段落与引用，结果只作工作集软提示。
  - `seedvr2_7b_sharp_fp8/`：SeedVR2 视频超分。
  - `demucs_audio/`：Demucs 人声/背景分离。
  - `stable_audio_3/`：Stable Audio 3 Medium 文生音频，目前只供 Playground。
  - `yue2/`：YuE2-3B 风格描述 + 歌词生成整首歌，只供 Playground；`skills/yue2-song-writing/` 是改写自官方的写作 Skill，经 Playground `audio_prompt` 交付。
  - `mock/`：测试用 mock 生成。

## default_model_providers_implement/ — Mac / Windows 模型服务（独立部署，不 import Core）

- `README.md`：部署、资源调度与各 worker 说明。
- `server.py`：HTTP 任务服务（submit/observe/cancel/artifact）与 runner 装配；H3 按 `submission_id` 与请求摘要去重，取消提交保存阻止迟到上传的取消记录。
- `resource_manager.py`：单个 lane 的互斥/定并发调度、同族驻留、切换释放与排队位置。
- `lane_dispatcher.py`：进程内多 lane 路由（lane 内 FIFO 与并发上限，lane 间互不等待）。
- `runners.py`：常驻 JSONL runner 与各模型 runner 工厂。
- `controller_lease.py`：控制方活性租约与失联释放；可选在租约丢失后通知服务退出。
- `task_store.py`：任务记录持久化（`runtime-state.json`），含 H3 提交摘要与请求准备中断的恢复。
- `request_builders.py`：各路由请求校验与任务目录写入。
- `strict_json.py`：严格 JSON 字段解析。
- `sampling_progress.py`：采样步速与剩余时间估算。
- `h3_request.py`：H3 runtime 内部请求 v6 的严格解析（任务目录内文件、基础模型与配套 20/8 步、Sage/SelfLift 开关、32 网格画布、17k+5 帧）。
- `comfy_core/README.md`、`comfy_core/runtime.py`、`comfy_core/worker.py`：固定图 Comfy Core 运行时（通用初始化与 H3 FL2VA/Ref2VA 执行）与 JSONL 入口（H3 或 Qwen Image）。
- `comfy_core/graph.py`：按 mode → 步数/权重 → 注意力 → SelfLift 现场构造并校验 H3 节点图。
- `comfy_core/qwen_image.py`：Qwen Image 2.1（NoctQ V4）固定节点图、进度映射与 Comfy Core 执行。
- `qwen_image_request.py`：Qwen Image runtime 内部请求的严格解析（任务目录内图片、32 网格画布）。
- `indextts2_worker.py`：IndexTTS2.5 独立 WSL JSONL worker，中英语言、语速与八维情感。
- `breeze_tts2_worker.py`：Breeze TTS 2 桥接 worker（按需拉起 WSL API）。
- `seedvr2_worker.py`：SeedVR2 超分常驻 worker。
- `codex_worker.py`、`agy_worker.py`：Codex / AGY 图片 worker（Mac）。
- `demucs_audio_worker.py`：音轨分离（Mac）。
- `stable_audio_3_worker.py`：Stable Audio 3 Medium 一次性生成（Windows 经 WSL、Colab 直接运行）。
- `yue2_worker.py`：YuE2-3B 一次性歌曲生成（Windows 经 WSL、Colab 直接运行）；歌词为空时先把乐谱人声旋律移到器乐声部，并把超长乐谱按整段收到 300 秒内。
- `yue2_instrumental/`：YuE2 官方纯音乐转谱脚本（MIT，原样，不参与 ruff）。
- `requirements-codex-image.txt`：私有图片服务依赖。
- `macos/install_launch_agent.sh`、`macos/launch-agent.plist.template`、`macos/run_codex_server.sh`：Mac 媒体服务 LaunchAgent 安装与启动。
- `macos/install_demucs.sh`：Demucs 独立虚拟环境安装。
- `colab/setup.sh`：前台准备 H3 Turbo V2 与共用权重，后台先准备其余能力，最后下载 Hybrid V2 与官方 BF16。
- `colab/setup_models.sh`：Colab 其余模型的固定版本、权重与独立运行环境。
- `whisper_runner.py`：Colab 同步 WAV 转写，使用部署时固定的 whisper.cpp CLI 和模型。
- `colab/node_status.py`：Colab 节点状态（模型服务、GPU、各权重是否就绪、任务、后台下载），供 `scripts/colab_node.sh status/watch` 远程调用。
- `colab/fetch_progress.py`：从 Hugging Face 多连接分块下载权重，以 GB、速度与预计剩余时间显示进度。
- `colab/run_server.sh`：Colab VM 上启停模型服务（回环地址 + Bearer Token）；VM 由 `scripts/colab_node.sh` 手动开关。
- `windows/install_scheduled_task.ps1`、`uninstall_scheduled_task.ps1`：Windows 计划任务安装与卸载。
- `windows/run_server.ps1`：Windows 服务启动。
- `windows/service_status.ps1`、`windows/stop_services.ps1`：状态查看与停止。
- `windows/run_breeze.ps1`：单独启动 Breeze API。
- `windows/configure_h3_defender_exclusions.ps1`：H3 权重的 Defender 排除项。
- `windows/run_ref2va_acceptance.ps1`：Ref2VA 真机验收。

## provider_tests/ 与 scripts/

- `provider_tests/`：插件请求翻译、线上协议、服务与 worker、bundle、黄金请求旅程等测试；`conftest.py` 复用同一工作区 Core 检出目录（默认 `../slatehand`）的测试支撑；`test_provider_boundary.py` 守卫插件只用 Provider SDK、模型服务不依赖 Core。
- `provider_tests/golden/provider_requests/`、`golden_provider_requests.py`：经完整 Core 旅程录制的插件线上请求黄金文件与录制设施。
- `provider_tests/fixtures/yue2/`：YuE2 乐谱夹具。
- `scripts/check.sh`：本仓库工程门禁。
- `scripts/ref2va_acceptance.py`、`scripts/seedvr2_upscale_acceptance.py`：真实媒体服务验收。
- `scripts/windows_node.sh`、`scripts/node_heartbeat.py`：手动启动 Windows 节点（经 SSH 运行仓库内固定脚本）后在前台持续维持控制租约；Ctrl-C 或关闭终端即释放，Windows 服务随租约丢失自行退出。
- `scripts/progress_view.py`：`colab_node.sh` 的显示过滤器：把下载进度行渲染成原地刷新的进度条（按终端显示宽度截断），并排版状态面板。
- `scripts/colab_node.sh`：手动开关 Colab 节点（开 G4、同步代码与 Token、安装并启动服务后进入状态面板，代码未变时不重启；status/watch 状态面板；down 回收 VM）。远程命令走 `colab exec`，不与 Core 的隧道争用唯一的 `colab ssh` 连接。
