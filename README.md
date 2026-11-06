# Slatehand Provider Example

[Slatehand（场记）](https://github.com/Slatehand/slatehand) 作者自用部署的完整 Provider 实现，也是编写自己
Provider 方案时的参考。Core 不认识这里的任何代码：启动时用 `--provider-dir` 指向本目录，Core 读取
[`slatehand-provider.toml`](slatehand-provider.toml)，导入其中声明的 bundle 工厂并安装插件。

## 组成

```mermaid
flowchart LR
    subgraph core[Slatehand Core]
        loader[server/provider_bundles.py]
        reg[ProviderRegistry]
    end
    subgraph example[本仓库]
        manifest[slatehand-provider.toml]
        bundle[slatehand_providers/bundle.py]
        plugins[slatehand_providers/plugins/*<br/>Core 侧插件]
        services[slatehand_providers/services.py<br/>随 Core 启停的部署服务]
        mac[default_model_providers_implement<br/>Mac 媒体服务 :8792]
        win[default_model_providers_implement<br/>Windows GPU 服务 :8791]
    end
    loader -->|--provider-dir| manifest --> bundle
    bundle --> plugins
    bundle --> services
    loader --> reg
    plugins -->|HTTP| mac
    plugins -->|HTTP + Bearer| win
    services -->|LaunchAgent| mac
    services -->|SSH 启停、控制租约| win
```

- `slatehand-provider.toml`：Core 读取的清单（bundle 名、工厂、import 路径、Core 环境需要的额外发行包）。
- `slatehand_providers/plugins/`：每个模型一个插件（manifest、请求翻译、HTTP 调用、随插件发布的提示词 Skill）。
  插件在 Core 进程里运行，只使用标准库与 Core 的 Provider SDK。
- `slatehand_providers/bundle.py`：`example` bundle，按优先级安装插件：Codex 先于 AGY 与 Qwen Image（生图/改图），
  Stable Audio 3 先于 YuE2（文生音频），Breeze 先于 IndexTTS2.5（声音克隆）。
- `slatehand_providers/deployment.py`、`services.py`：读取本机部署配置，并提供随 Core 启停的服务。
- `default_model_providers_implement/`：Mac 与 Windows 上运行的模型服务，独立部署，不 import Core。
  部署、资源调度与各 worker 见其 [README](default_model_providers_implement/README.md)。
- `provider_tests/`：插件、服务、bundle 与黄金请求旅程的测试。
- `scripts/`：工程门禁与真实媒体服务验收脚本。

## 工作区与安装

本仓库与 Core 放在同一个工作区，测试会复用 Core 检出目录里的测试支撑：

```text
SlatehandWorkspace/
├── slatehand/                      Core
└── slatehand-providers-example/    本仓库
```

本仓库自己的虚拟环境用于测试和 Mac 模型服务：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '../slatehand[dev]' -e '.[services]'
./scripts/check.sh
```

插件只需要标准库与 Core 的 Provider SDK，Core 自己的虚拟环境不需要额外安装任何东西。

## 启动

在 Core 目录：

```bash
./start.sh --provider-dir ../slatehand-providers-example
```

或在 Core 的 `start.local.env` 写 `SLATEHAND_PROVIDER_DIRS=../slatehand-providers-example`，之后直接 `./start.sh`。

## 本机部署配置

bundle 从本目录读取部署配置，全部被 Git 忽略：

- `provider.local.env`：Windows 节点地址、SSH 别名、Windows 上本仓库路径、Mac 端口与 Whisper 等，模板见
  [`provider.local.env.example`](provider.local.env.example)；未知键直接报错，同名进程环境变量优先。
- `var/secrets/windows-model-service-token`：Windows 服务的 Bearer Token。只有这个文件存在时才接入 Windows 节点。
- `var/whisper-asr/ggml-large-v3-turbo-q5_0.bin`：本机 Whisper 默认模型。

随 Core 启停的服务按顺序为：

```mermaid
sequenceDiagram
    participant C as Core
    participant B as example bundle
    participant W as Windows 节点
    participant M as Mac LaunchAgent
    participant A as whisper-server
    C->>B: create_bundle(context)
    B-->>C: 插件 + 服务
    C->>W: SSH 运行 install_scheduled_task.ps1，等待 8791 与 Breeze 可达
    C->>W: 控制租约 acquire，之后每 5 秒 heartbeat
    C->>M: install_launch_agent.sh，等待 8792 可达
    C->>A: 启动 whisper-server，等待模型加载（最长 240 秒）
    Note over C: 任一服务启动失败：逆序关闭已启动的服务，Core 退出
    C->>A: 退出时逆序关闭：停止 Whisper、卸载 LaunchAgent、释放租约、SSH 运行 stop_services.ps1
```

`SLATEHAND_AUTOSTART_WINDOWS_PROVIDER=0` 时不经 SSH 启停 Windows 服务，只维持控制租约；
`SLATEHAND_AUTOSTART_MAC_PROVIDER=0` 时不安装 LaunchAgent（非 macOS 上始终不安装）。

## 编写自己的 Provider 方案

照这里的结构另起一个目录：根部放 `slatehand-provider.toml`，插件只 import Core 的 Provider SDK，
提供 `create_bundle(context) -> ProviderBundle`，从 `context.provider_directory` 读取自己的配置。步骤与代码骨架见
Core 仓库的 `slatehand-provider-plugin` Skill（`.agents/skills/slatehand-provider-plugin/`）。

## Breeze-TTS-2 接入

默认部署用 `SLATEHAND_BREEZE_ENDPOINT`（默认同 Windows 服务地址）连接同一受认证模型服务；Breeze runtime 由 `exclusive_gpu` 调度器按需启动，不会在开机时加载，也不会与 H3 同时驻留。它仍复用已有的 WSL 中已有的 `breeze-tts/.venv` 和模型目录，不会 clone、创建 venv、安装依赖或使用 Docker。手工启动官方 API 仅用于兼容旧部署：

```text
cd ~/ai/breeze-tts
.venv/bin/python -m breeze_infer.api ~/ai/models/Breeze-TTS-2 --host 0.0.0.0 --port 7860
```

随后在 `provider.local.env` 设置 `SLATEHAND_BREEZE_ENDPOINT`。音色设计与声音克隆都走 Breeze TTS 2；Clone/Direction 请求必须保存参考音频完整文字稿。Breeze 只在真实任务期间启动，H3 请求进入队列时调度器先释放 Breeze；不应再注册独立的 `Slatehand Breeze TTS 2` 开机任务。

## Whisper ASR 接入

Whisper 插件连接本机 `whisper.cpp` server，为 Breeze Reference Voice 提供中英文自动转写候选。发现
`whisper-server`（PATH 或 `SLATEHAND_WHISPER_SERVER`）和模型文件（默认 `var/whisper-asr/ggml-large-v3-turbo-q5_0.bin`，
或 `SLATEHAND_WHISPER_MODEL`）时，bundle 随 Core 在 `127.0.0.1:8793` 拉起：

```text
whisper-server --host 127.0.0.1 --port 8793 \
  --model var/whisper-asr/ggml-large-v3-turbo-q5_0.bin \
  --language auto --flash-attn
```

已有自己运行的服务时设置 `SLATEHAND_WHISPER_ENDPOINT`，bundle 只连接、不启停。服务只绑定回环地址。
识别结果仅回填 Web 文本框，用户校对并提交 Breeze 后才进入业务状态；Agent 没有 ASR 入口或自动转写提示。

## 第三方内容

随插件发布的官方 Skill、模板与转谱脚本按各自许可证使用，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
