# 第三方来源说明

本仓库自身代码与文档以 Apache License 2.0 发布（见根目录 `LICENSE`）。下列第三方材料按各自许可证使用，
不因随本仓库分发而改为 Apache-2.0。

## MiniMax H3 官方 Prompt Skill

- 上游仓库：https://github.com/MiniMax-AI/MiniMax-H3（`skills/h3-prompt-writing/`）
- 固定版本：`a107547fa669c509b8e6363fe18378d46ab3066c`
- 上游许可证：MiniMax H3 Community License Agreement（全文见本仓库路径下的 `LICENSE`）
- 本仓库路径：`slatehand_providers/plugins/minimax_h3/skills/h3-prompt-writing/`

`references/base-en.txt`、`references/ref-en.txt` 与 `SKILL.md` 在上游基础上做了修改（正文语言跟随用户、
音效必写、默认不生成非画内配乐，以及 Slatehand 的导演边界、旁白隔离与对白音频显式引用规则），`agents/openai.yaml` 未修改，
`references/cinematic-video-prompting.md` 为 Slatehand 独立编写。逐文件修改说明与上游要求的版权声明见同目录
`NOTICE`。该协议对适用地区、使用限制和高收入商用另有约定，使用者须自行遵守。

## SeedVR2 私有部署依赖

- 上游实现：https://github.com/itontonpi/seedvr2
- 上游许可证：Apache License 2.0
- 权重镜像：https://www.modelscope.cn/models/numz/SeedVR2_comfyUI
- 使用范围：私有 Windows 默认模型服务的外部运行时

本仓库不包含 SeedVR2 上游源码或模型权重，只包含独立编写的模型级 HTTP 插件、严格请求构造和
常驻 worker 启动适配。部署者仍须分别遵守上游实现与模型权重页面声明的许可证和使用条件。

## YuE2 私有部署依赖

- 上游实现：https://github.com/multimodal-art-projection/YuE（`yue2_infer` 0.1.5）
- 上游许可证：代码 Apache License 2.0；`m-a-p/YuE2-3B` 与 `m-a-p/YuE2-Vae` 权重为 CC BY-NC 4.0 附加创作者许可
  （见权重仓库 `LICENSE`）
- 权重镜像：https://www.modelscope.cn/models/m-a-p/YuE2-3B 、https://www.modelscope.cn/models/m-a-p/YuE2-Vae
- 使用范围：私有 Windows 默认模型服务的外部运行时，仅 Playground 歌曲生成

本仓库不包含 YuE2 上游源码、推理包或模型权重，只包含独立编写的模型级 HTTP 插件、严格请求构造和
一次性 worker 启动适配。部署者仍须遵守权重许可证的非商用与署名条件。

## YuE2 官方 Agent Skill

- 上游仓库：https://github.com/multimodal-art-projection/YuE（`skills/yue2-music/`）
- 固定版本：`1116bea76032bee5668e5f097294d082fa0b84f0`
- 上游许可证：Apache License 2.0（全文见本仓库路径下的 `LICENSE`）
- 本仓库路径：`slatehand_providers/plugins/yue2/skills/yue2-song-writing/`

`SKILL.md` 由 Slatehand 用中文改写：只保留风格描述与分段歌词的写法，删除本地安装、脚本、乐谱编辑、翻唱与听感对比
流程，增加 Playground 参数映射与能力边界；风格示例原样取自上游 `assets/prompt.json`。逐项修改说明见同目录 `NOTICE`。

## YuE2 官方纯音乐转谱脚本

- 上游仓库：https://github.com/multimodal-art-projection/YuE（`skills/yue2-music/instrumental/scripts/`）
- 固定版本：`1116bea76032bee5668e5f097294d082fa0b84f0`
- 上游许可证：MIT License，Copyright (c) 2026 yue2-music contributors（全文见本仓库路径下的 `LICENSE`）
- 本仓库路径：`default_model_providers_implement/yue2_instrumental/`

`abc_tools.py`、`compile_score.py`、`common.py`、`instrumentalize.py` 按字节原样保留，未修改；只由私有模型服务的
`yue2_worker.py` 在纯音乐请求中调用 `convert_score`。同目录 `README.md` 由 Slatehand 编写。

## whisper.cpp 本机 ASR 依赖

- 上游实现：https://github.com/ggml-org/whisper.cpp
- 上游许可证：MIT License
- 默认模型：`ggml-large-v3-turbo-q5_0.bin`
- 模型来源：https://huggingface.co/ggerganov/whisper.cpp
- 使用范围：本机 Apple Silicon Reference Voice 中英文转写服务

本仓库不包含 whisper.cpp 源码、二进制或模型权重，只包含独立 HTTP Provider adapter、
人类 UI 触发入口与启动配置。识别文字是可编辑候选，不作为未经确认的项目事实。

## Qwen Image 2.1 官方提示词模板与 NoctQ V4 权重

- 上游仓库：https://github.com/QwenLM/Qwen-Image-2.1
- 上游文件：`prompt_rewrite/prompts/system_prompt_t2i.txt`、`prompt_rewrite/prompts/system_prompt_edit.txt`
- 固定版本：`7307809d2c9d582be700a1b9b04d393fc9cdf865`
- 上游许可证：Qwen RESEARCH LICENSE AGREEMENT（仅限非商业的研究与评估用途；分发须附协议副本、NOTICE 与修改说明）
- 本仓库路径：`slatehand_providers/plugins/qwen_image/skills/qwen-image-prompt-writing/references/t2i-en.txt`、`edit-en.txt`
- SHA-256：`t2i-en.txt` `a77c9a06c59b120741141d9514b95682bb8761d02bec49ca61def7b2b3d9fb99`；
  `edit-en.txt` `e378fea686a1431581ba4c654d332ae96adad633f144ae738ec8ce9c4fd66439`

两个模板按字节原样引入，Slatehand 的适配规则写在同目录 `SKILL.md`，不修改原文；协议全文与上游要求的
版权声明见 `slatehand_providers/plugins/qwen_image/skills/qwen-image-prompt-writing/` 下的 `LICENSE` 与 `NOTICE`。
这两个模板只可用于非商业用途，商用须另行取得 Qwen 授权。私有 Windows 服务使用的 NoctQ V4
（`NoctQ_V4_int8_convrot.safetensors`）是 Qwen Image 2.1 的 Civitai 社区微调权重，本仓库不包含
任何 Qwen 权重。

Slatehand 独立编写的适配层将参考图写作规则统一到全局 `slatehand-image-prompt-writing`：
逐图说明用途、正文显式引用插件标签、引用说明不含文件名；Qwen 专用层保留 `<imageN>`、单图“图片”与画幅约定。
上述调整不修改两个上游模板原文或许可证。
