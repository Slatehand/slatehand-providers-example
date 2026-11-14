# 默认部署插件与服务的测试

本目录测试本仓库的插件、bundle、部署服务与 Mac/Windows 模型服务；`conftest.py` 复用同一工作区 Core 检出目录
（默认 `../slatehand`，可用 `SLATEHAND_CORE_DIR` 指定）里 `tests/` 的测试支撑。全部测试只用合成媒体与录制 transport，
不调用真实模型。

黄金请求 `golden/provider_requests/{project,playground}.json` 由 `test_golden_provider_requests.py` 经完整 Core 旅程逐字节校验
插件发出的线上请求；媒体字节规范化为标签、SHA-256 与字节数。`SLATEHAND_UPDATE_GOLDEN=1` 重录，只用于有意改变线上请求并经审查的提交。

## 插件行为与自动化守护

规则编号沿用 Core 仓库 `tests/provider-behavior-contract.md` 的 Provider 行为契约，便于对照。

| 规则 | 当前行为 | 实现位置 | 自动化守护 |
| --- | --- | --- | --- |
| A4 | H3 实例设置声明 480p/720p/1080p、Hybrid 20 步/Turbo 8 步/官方 Pruned BF16 20 步、SageAttention 和 SelfLift；预设把基础模型（线上 `base_model`）与步数绑定；严格字段与持久化。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`render.py`、`contracts.py` | `test_provider_settings.py::test_settings_validation_is_exact_and_typed`、`::test_h3_preset_binds_base_model_and_steps`、`test_h3_render_settings.py::test_official_pruned_bf16_preset_is_twenty_steps_with_its_own_base_model`、`test_h3_request_schema.py::test_base_model_must_be_known_and_match_steps`、`::test_provider_settings_http_is_strict_and_persistent`、黄金 `settings.h3_turbo_1080p` 与 Playground 480p/1080p 步骤 |
| A4a | H3 与 Breeze 设置 `node` 在本地 Windows 与 Colab G4 之间切换新提交；运行中任务按句柄回到提交节点；未接入的节点提交即报错。 | `slatehand_providers/plugins/nodes.py`、两个插件的 `manifest.py`/`plugin.py`、`slatehand_providers/bundle.py` | `test_h3_nodes.py` |
| A5 | H3 画布由插件按画幅/分辨率计算，采用 32 像素网格，边长 ≤1920、像素 ≤2.1M。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`render.py` | `test_provider_settings.py::test_h3_render_canvas_tiers_follow_the_32_pixel_grid`、黄金（9:16/2:1/16:9 × 480p/720p/1080p 中的 6 组） |
| B7 | H3 Ref2VA 声明最多 4 张附加图、不重复、必填说明 ≤2000 字。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_director_commands.py`、`video.test.tsx`“Ref2VA 在首尾帧右侧…必填描述” |
| B8 | H3 Ref2VA 声明 0–3 条 WAV 参考音频、不重复、必填说明、不限时长。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_prompt_worksets.py::test_ref2va_submits_additional_images_without_reference_audio`、`::test_ref2va_reference_audio_has_no_duration_limit`、黄金 Playground `video.ref2va.no_audio` |
| B9 | H3 Ref2VA 声明 0–3 条 MP4 参考视频、2–15 秒、不重复、必填说明；不引入其音轨。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_workflow_gates.py::test_video_reference_gate_checks_mp4_duration_window`、`test_prompt_worksets.py::test_ref2va_submits_reference_videos_with_lineage`、`video.test.tsx`“Ref2VA 参考视频只列 2–15 秒 MP4…”、“达到 3 条上限…” |
| B14 | 视频时长取 Segment 的有限值且 ≥0.2 秒；H3 不设上限。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | `test_provider_contracts.py::test_h3_requests_have_no_duration_upper_limit`、黄金 16.5 秒 |
| B17 | H3 插件固定 cfg 1.0 与输出音轨开关，项目和 Playground 一致。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`requests.py`、`contracts.py` | 黄金 |
| C4 | 旁白轨道 recipe_params 保存机制参数；Breeze 的 performance_instruction 是 ≤200 字或 null 的 recipe 字段。 | `slatehand_providers/plugins/breeze_tts2/manifest.py`、`provider.py` | `test_performance_instruction.py`、`test_recipe.py` |
| C8 | Breeze 插件固定 cfg_scale 4.0；正文 ≤20000、instruction ≤4000，克隆要求参考文字稿。 | `slatehand_providers/plugins/breeze_tts2/manifest.py`、`provider.py` | `test_breeze_tts2_provider.py`、`test_recipe.py`、`test_golden_provider_requests.py` |
| C9 | Breeze 异步 API 明确返回 400/404/405/415 时回退官方同步 API，PCM 保存为可观察/回收的 WAV 句柄。 | `slatehand_providers/plugins/breeze_tts2/manifest.py`、`provider.py` | `test_breeze_tts2_provider.py` |
| D1 | Codex/AGY 插件固定图片 model，声明生图 ≤5 张参考、改图底图加 ≤4 张参考，接受 PNG/JPEG/WebP。 | `slatehand_providers/plugins/codex_image/manifest.py`、`provider.py`；`agy_image/` | `test_provider_contracts.py::test_image_*`、黄金 |
| D8 | Qwen 插件全局设置声明分辨率档位、CFG、步数与负向提示词；画布长边取档位、短边按比例对齐 32，显式宽高须同时填写；改图底图在输入首位；HTTP 请求、状态、取消、产物与句柄严格校验。 | `slatehand_providers/plugins/qwen_image/` | `test_qwen_image_provider.py::test_canvas_*`、`::test_explicit_size_*`、`::test_edit_request_*`、`::test_invalid_size_*`、`::test_provider_wire_*` |
| D9 | Windows `qwen_image` 服务封闭请求、只解析任务目录内图片、固定节点白名单图与单调进度。 | `default_model_providers_implement/{request_builders.py,qwen_image_request.py,comfy_core/qwen_image.py,server.py,runners.py}` | `test_qwen_image_provider.py::test_prepare_*`、`::test_internal_request_*`、`::test_fixed_graph_*`、`::test_progress_*` |
| D11 | 图片比例词汇在 Core、Mac 服务、Codex worker 与 MCP 一致；Keyframe 不带比例，造型设定图与地点全景图固定 2:1。 | `core/model_providers/manifest.py`；`default_model_providers_implement/strict_json.py`、`codex_worker.py`；`integrations/slatehand_mcp/production_tools.py`；`models/validation/generation.py` | `test_image_aspect_ratios.py::test_aspect_ratio_vocabulary_is_identical_everywhere` |
| E4 | Stable Audio 3 文生音频使用 prompt ≤1000、时长 1–380 秒与 seed，只供 Playground。 | `slatehand_providers/plugins/stable_audio_3/`；`core/playground/capabilities.py` | `test_stable_audio_3_provider.py`、黄金 `audio.generate` |
| E4a | YuE2-3B 歌曲生成使用风格描述 1–1000 字、歌词 ≤4000 字（可空）与 seed，产物为 48 kHz 立体声 WAV，只供 Playground；乐谱、CFG 与采样参数不进入请求；歌词为空时模型服务把内部乐谱的人声旋律移到器乐声部、记谱超过 300 秒时保留首末段删去中间整段后再生成，有歌词时不改谱。 | `slatehand_providers/plugins/yue2/`；`default_model_providers_implement/yue2_worker.py`、`yue2_instrumental/` | `test_yue2_provider.py`（含真实模型乐谱 fixture） |
| E5 | Whisper ASR 接受 WAV 与 auto/zh/en，同步返回文字，不产生 Asset。 | `slatehand_providers/plugins/whisper_asr/`；`core/structured_director/service.py` | `test_whisper_asr_provider.py`、黄金 multipart |
| G4 | 所有插件拒绝 plugin_id 或版本不匹配的句柄。 | 各插件 `provider.py` 的句柄校验 | `test_model_provider_contract.py`、各插件测试 |
| H3 | H3 默认优先 `minimax_h3.ref2va`；官方格式 Skill 与角色视觉锚点规范位于 `minimax_h3` 插件包。 | `slatehand_providers/plugins/minimax_h3/manifest.py`、`skills/h3-prompt-writing/` | `test_h3_prompt_skill.py`、`test_h3_prompt_writer.py`、`test_golden_provider_requests.py` |
| J1 | 插件包安装后声明声音克隆、语速 0.5–2 与八维情感 −1–1；无 Core 领域或 Web 专用实现。 | `slatehand_providers/plugins/indextts2/` | `test_indextts2_provider.py::test_plugin_loads_playground_vector_form_and_preserves_historical_request`、`::test_narration_uses_new_plugin_without_domain_changes` |
| J2 | 模型 HTTP 请求体、五种状态、取消、回收、句柄与响应严格校验。 | `slatehand_providers/plugins/indextts2/` | `test_indextts2_provider.py::test_observe_translates_all_phases`、`::test_invalid_observation_is_rejected`、`::test_cancel_artifact_and_handle_boundaries` |
| J3 | Windows 服务路由、封闭内部请求、63 位 seed 与中英语言映射。 | `default_model_providers_implement/{server.py,request_builders.py,indextts2_worker.py,runners.py}` | `test_indextts2_runtime.py` |
