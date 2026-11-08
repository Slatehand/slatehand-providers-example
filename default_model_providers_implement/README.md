# 私有默认模型服务

本目录是当前开发自用的默认实现，不属于 Slatehand 开源 Core，也不是用户必须实现的公共 Provider
contract。Core 只通过 `core/model_providers/<具体模型>/` 中的插件调用各自独立 HTTP API。

## 部署拓扑

```text
Mac
├── Slatehand Core（后续）
└── Codex image / AGY image / Demucs audio service
    ├── 127.0.0.1:8792
    └── lanes: network_image(4) / mac_heavy(1)

Windows（LAN）
└── H3 / IndexTTS2.5 / SeedVR2 / Stable Audio 3 / YuE2 / Qwen Image service
    ├── <windows-lan-ip>:8791
    ├── Bearer Token
    └── resource: exclusive_gpu
└── Breeze TTS 2（由同一 exclusive_gpu 调度器按需启动）
    └── WSL eth0 地址:7860（仅本机 NAT 网段可达，仅在 Breeze 任务期间存在）
```

Windows 与 Mac 服务显式启用不同能力。禁用能力的路由返回 404；Core 不能根据相同 server 实现推断
这些 API 存在公共任务层。

Windows 服务内部只有一个 `exclusive_gpu` 执行槽。当前模型族完成任务后继续驻留；相邻同族任务复用
同一 runtime，只有队列切换到另一模型族、任务被取消或服务关闭时才释放。这个生命周期是私有部署细节，
不会出现在 Core 的模型插件接口里。

Windows 默认启动还要求 Mac 侧持有一个短期控制租约：由人手动运行的 `scripts/windows_node.sh up` 在后台启动
`scripts/node_heartbeat.py`，每 5 秒 heartbeat；调用方退出时主动释放，失联 20 秒时 Windows 自动停止接收新任务、
取消运行中及排队任务，并通过 GPU 调度线程释放驻留 runtime。Windows 以 `--exit-when-controller-lost` 启动，
租约释放或超时后服务进程随即以退出码 0 关闭（`run_server.ps1` 不重启）。Core 本身不持有租约。任务记录保留明确的
`controller_lease_released` 或 `controller_lease_expired` 原因，心跳恢复后可以显式创建新的 Generation 重试。租约接口复用 Bearer Token，只接受固定的随机 Session ID，不接受
路径、模型参数或命令。它只是当前 Mac + Windows 默认部署的控制面，不是公共 Provider contract。

## Windows

`windows/install_scheduled_task.ps1` 会：

1. 预检 ComfyUI Python、固定 Comfy Core revision、SeedVR2 Python、仓库与两个固定权重；
2. 在 `E:\SlatehandModelProviders\service-token.txt` 创建随机 Token（已存在则保留）；
3. 注册 `Slatehand Default Model Providers` S4U 开机任务；
4. 失败时最多每分钟重启一次，共三次；
5. 仅把当前固定图使用的六个 H3 权重文件加入 Defender 排除，并在卸载时只撤销本脚本实际新增的条目；
6. 启动 `mock,h3_fl2va,h3_ref2va,breeze_tts_2,indextts2,seedvr2_7b_sharp_fp8,stable_audio_3,yue2,qwen_image`，不启动 Codex 图片生成或编辑；Breeze 不注册独立计划任务，由 `exclusive_gpu` runtime 按需加载并在切换到 H3 等模型族前释放。`stable_audio_3` 与 `yue2` 与它们共用这一张卡，每个任务在 WSL 里一次性生成后退出。

服务在状态目录维护 `service.pid`。安装或卸载只会在该 PID 的 Windows 命令行确认包含 Slatehand 模型
服务模块后终止进程，避免计划任务停止 PowerShell 后遗留旧 Python 子进程，也避免误杀无关进程。

安装、检查和卸载入口：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\install_scheduled_task.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\service_status.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\stop_services.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\uninstall_scheduled_task.ps1
```

`run_server.ps1` 把服务 stdout/stderr 写入状态目录的 `server.out.log` / `server.err.log`，每次启动前把上一次运行（可能是崩溃的那次）轮转为 `.prev.log`。计划任务的 `RestartCount` 只覆盖启动失败，不覆盖运行后退出，因此脚本自己守护服务：非零退出后 10 秒重启，10 分钟内超过 5 次则放弃并以该退出码结束。`stop_services.ps1` 与安装脚本先停止计划任务（即这层守护）再结束服务进程，主动停止不会被拉回。

`stop_services.ps1` 只停止当前运行的 Windows Model Provider、Breeze 和受管 ComfyUI 进程，保留计划任务。
计划任务配了失败自动重启（每分钟一次、共三次），因此脚本在结束进程之后会再停一次任务压掉已排队的重启，
并按固定服务模块名清理孤儿进程，最后确认进程与监听端口都已释放，否则直接报错而不是静默留下 GPU 服务。
该目录下的 `.ps1` 必须保持纯 ASCII：Windows PowerShell 5.1 会把无 BOM 的脚本按 ANSI 解码，非 ASCII 注释会破坏语法。
需要强制清理时可手工经 SSH 调用它。`uninstall_scheduled_task.ps1` 才会删除计划任务，不能作为日常关闭入口。

安装脚本默认使用 `127.0.0.1`。LAN 部署须由部署者明确批准，例如：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\install_scheduled_task.ps1 -ListenAddress <windows-lan-ip>
```

脚本只接受上述回环地址或指定 LAN 地址，不允许 `0.0.0.0`。当前防火墙规则名为
`Slatehand Model Providers 8791`，只允许 TCP 8791、本机 `<windows-lan-ip>/32`、远端 `LocalSubnet`；因为
当前以太网被 Windows 标记为 Public，该精确规则应用于 Private+Public profile，但不允许非本地子网。
LAN 模式仍强制 Bearer Token。

卸载只删除计划任务，不删除代码、任务状态或 Artifact。Token 不得提交、打印或写入日志；Mac 侧副本
应放在 Git 忽略的 `var/secrets/`。

服务重装后继续监听指定 LAN 地址：未认证请求返回 401，带 Token 的模型路由可达，Windows 未启用的 Codex image 路由返回 404。

### Colab 节点

同一服务也可以在 Colab VM（Linux）上只启用 `h3_fl2va,h3_ref2va,breeze_tts_2`：`colab/setup.sh` 安装与 Windows
相同 revision 的 ComfyUI / comfyui-SelfLift 和 `sageattention==1.0.6`（保留 Colab 自带的 CUDA 版 torch），从固定 commit
的 Hugging Face 仓库多连接下载权重到本地盘，并按 Windows 节点相同的相对路径链接进 `ComfyUI/models`；Breeze TTS 2 使用上游
`breezeblue-ai/breeze-tts` 固定 revision 与独立的 Python 3.12 venv（依赖按其 `requirements.txt`），worker 在 Linux
上直接以独立进程组启动 `breeze_infer.api --fast-all`，不经 WSL。`colab/run_server.sh` 以独立进程组在
`127.0.0.1:8791` 启动服务，Token 来自 `/root/.slatehand-colab-token`。固定图里带子目录的模型名按宿主系统的
路径分隔符生成，Windows 与 Linux 共用同一份 `comfy_core`。Colab 节点不启用控制租约；VM 由人用
`scripts/colab_node.sh` 手动开关。

### H3 Runtime

- 执行边界：FL2VA 与 Ref2VA 只通过 `comfy_core/` 在各自的隔离子进程内执行 Slatehand 现场构造的固定
  节点图，不启动 ComfyUI HTTP、Web UI、数据库或队列，不扫描 custom nodes，只显式加载
  `comfyui-SelfLift` 一个包。Core 仍只看到模型级 H3 Provider；用户不能提交任意 graph、节点、模型路径或
  输出路径。旧的原生 H3 worker 与独立 ComfyUI HTTP 回退路径已删除，不存在隐藏 fallback；
- 部署固定：ComfyUI revision `a7169322`、`comfyui-SelfLift` revision `835c3cf7`，由安装脚本预检；
  Python 由管理员通过 `SLATEHAND_H3_PYTHON` 固定；
- 组合项：请求（内部 v6）只能选择 mode（FL2VA/Ref2VA）、`base_model` 与配套 `steps`、`sage_attention`、
  `selflift` 和画布；决策顺序为 mode → 基础模型/步数/权重 → 注意力 → SelfLift：
  - `dasiwa_hybrid_v2`（20 步）：`DasiwaMinimaxH3_dasiwaHybridV2_int8`；单阶段 `res_multistep`，SelfLift 时
    `euler` 10+10；
  - `dasiwa_turbo_v2`（8 步）：`DasiwaMinimaxH3_dasiwaHybridTurboV2_int8`（独立权重，不叠加 Turbo LoRA）；
    `euler`，SelfLift 时 4+4；
  - `official_pruned_bf16`（20 步）：官方 `minimax_h3_{fl2va,ref2va}_pruned_bf16`，按 mode 各一份；采样同
    20 步，与官方模板一致（`BasicGuider`、`res_multistep`/`simple`、无 shift）。只部署在 Colab 节点；节点缺少
    所选权重时任务直接失败并说明，不回退到其它权重；
  - 各基础模型共用 NVFP4 Qwen3-VL 文本编码器、独立视频/音频 VAE，不再有 SigmaShift；
  - `ModelAttentionBackend` 选 `sage attention` 或 `default attention`。Sage 不可用（未安装或 Triton 缓存
    不可写）时任务直接失败并说明原因，不回退到默认注意力，也不标成 Sage 成功；
  - SelfLift 固定 `cfg=1`、`lowres_scale=0.5`、`rho=0`、`w_min=0.5`、`w_max=1`、
    `minimax_h3_latent_upscaler_3d_conv_v1_fp16`、不分块、放大后卸载；关闭时图中不保留放大器节点；
- 画布：必须落在 32 像素网格（16 倍潜变量下采样后还要 2×2 patchify；FL2VA+SelfLift 在
  848×480、1280×720 上会 reshape 失败）。Core 全局分辨率档位给出 480p `864×480`、720p
  `1280×704`（默认）、1080p `1920×1088`（竖屏宽高对调）；2:1 依次为 `960×480`、`1408×704`、`1920×960`
  （边长上限 1920）。最终装配与 Animatic 统一缩放裁切到 16:9 `1920×1080`、9:16 `1080×1920`、2:1 `1920×960`；
- 帧数：24 FPS，向上对齐为 `17k + 5`（请求 15 秒实际 362 帧、15.083 秒）；时长不设上限，只要求不短于 0.2 秒，
  15 秒是 Agent 侧软约束；
- 结果：完成消息写明实际画布、帧数与秒数、权重、采样器与步数、注意力后端，再接生成总用时，经
  Provider `observe` 显示在候选上；
- 显存：16 GB 开发卡上 15 秒 1080p + Turbo + SelfLift 已知在高分辨率第 1 步 OOM，720p 可完成。
  OOM 返回明确错误和当前配置，不自动降档，是否降低分辨率由用户决定；
- 生命周期：外层 Provider HTTP 服务与互斥调度器常驻。FL2VA 和 Ref2VA 各有一个逻辑 runner，相邻同
  mode 任务复用对应 Comfy Core 子进程；FL2VA/Ref2VA 互相切换，以及切换到其它模型族、失败、取消、
  服务关闭或 Mac Core 租约失效时都会结束当前进程，由操作系统完整回收 Private Commit；
- 内存：保留固定 ComfyUI revision 的默认 DynamicVRAM 和 RAM-pressure cache，不从 Slatehand 注入内存管理
  monkey patch；SageAttention 的 Triton 缓存固定在服务状态目录 `resident-runtimes/triton-cache`；
- 原生启动错误：只有采样前的已知 Windows access violation 允许自动重建一次；
- 稳定性：Python 读取大权重期间的系统崩溃曾落在 Windows `FLTMGR` 回调栈（Defender 过滤），因此部署脚本
  只排除当前固定图使用的六个精确权重文件，不排除 Python、任务目录、整个 ComfyUI 或整个 models 目录；
  脚本以本机状态记录自己新增的项，避免卸载时移除管理员原有配置，并撤销自己曾为已弃用旧权重添加的项；
- 输出：固定图 `SaveVideo` 产出 MP4，runtime 校验后复制到任务目录。

Ref2VA 使用官方 `MiniMaxH3ReferenceToVideo`：所选首帧、尾帧按顺序映射为 `<Picture 1>`、
`<Picture 2>`，随后按 Core 顺序追加最多 4 张视频附加参考图；Segment 可不提供参考音频，也可把显式选择的参考音频按相同稳定顺序映射为 `ref_audio_N`，并与 Prompt 的 `<Audio N>` 对应。已添加音频的用途完全由对应的必填说明表达。Core 还可按稳定顺序提供最多 3 条 2–15 秒参考视频，内部请求落盘为 `video-N.mp4` 并与 Prompt 的 `<Video N>` 对应；worker 解码抽帧后经 video VAE 编码为 `kind: "video"` 参考条件（位于图片之后、音频之前），不引入其音轨。Prompt 中的时间对齐语句负责让边界参考图接近精确地落到目标
首尾时刻；这是已验证的 H3 用法，不修改官方 latent。Provider 保留首尾槽位的
业务语义，但不把模型的提示词服从性宣称为像素级硬约束。

### IndexTTS2.5 Runtime

`/indextts2/speech` 接受正文、参考音频字节、63 位 seed、语速因子、八维情感与可选语言 auto/zh/en；
不接受模型目录、设备或 Shell 参数。默认仓库为 `E:\Project\index-tts`，权重在 `checkpoints/`，
使用 Ubuntu WSL 中 `.venv/bin/python` 与已部署的 `indextts.infer_v2_5`，不在任务期间安装依赖或下载模型。
语言 auto 映射模型的 zhen；正文语言由 Core 的语义角色提供，英文旁白使用 en。

独立 JSONL worker 按需加载，连续任务复用，切换模型族、取消或 Core 租约释放时退出并释放 GPU；
与 H3、Breeze、SeedVR2 共用 exclusive_gpu，不允许并发占卡。Python/Torch 使用完整 seed，
NumPy 取 seed mod 2^32，以适配它的 32 位范围。GPU 或依赖失败返回明确任务错误，不隐藏回退。

example bundle 在配置了 Windows 节点时一并安装 IndexTTS2.5 插件，复用同一 Token 与租约；
人类在 Provider 设置页选择声音克隆能力的绑定。该选择只影响新提交。

### Breeze TTS 2 Runtime

Breeze 是 WSL 内的既有部署（固定仓库、venv 与模型目录），worker 不克隆仓库、不安装依赖。调度器
首个 Breeze 任务到来时，`breeze_tts2_worker.py` 以 `--fast-all` 在 WSL 的 eth0 地址 `:7860` 拉起
`breeze_infer.api` 并直连该地址；相邻 Breeze 任务复用该进程，切换到其它模型族、取消或服务关闭时结束它。
WSL NAT 模式的 localhost 转发在虚拟机冷启动后可能不建立，因此不使用 Windows 侧 `127.0.0.1`；eth0 地址
只在 Windows 主机与 WSL 之间的 NAT 网段内可达，局域网无法访问。

Breeze API 的 stdout/stderr 追加写入 `resident-runtimes/breeze-api.log`（每次启动写分隔行，超过 16 MiB 时从头写），
启动失败的错误消息附带日志末尾。启动期以退出码 139（段错误）或 132（非法指令）退出时，通常是 WSL 虚拟机的 GPU 半虚拟化失效，
同一虚拟机内重试必然再崩：worker 执行 `wsl --terminate` 重启发行版后重试一次，仍失败才报错。exclusive_gpu
保证此时没有 IndexTTS2 等其它 WSL runtime 在运行。

`--fast-all` 为文本编码、backbone prefill/decode、depth decoder 与 codec 全部启用 CUDA Graph / 编译路径，
不改变模型与权重。当前 16 GB 开发卡上冷启动（加载 + 预热）约 70 秒，生成耗时约为音频时长的 0.48 倍，
显存峰值约 15.9 GB 且与文本长度无关。

纯 Voice Clone（没有表演指示）使用 Breeze 的 `ref_clone_tata` 模板；该模板没有 CFG 负向分支，worker
固定以 CFG 1 调用。带表演指示的 Voice Direction 使用 `ref_edit_tata`，继续采用插件配置的 CFG。

同一进程内相同输入与 seed 产生相同 token；进程重启后不保证相同，因此 seed 只记录本次提交，
不承诺跨重启逐字复现。显存几乎占满整卡，Windows 上不得有其它 GPU 常驻程序；
启动失败（含 OOM）时任务直接报错，不回退到 eager。

### SeedVR2 7B Sharp FP8 Runtime

SeedVR2 是独立的 `seedvr2.7b-sharp-fp8` 模型插件和 `/seedvr2/7b-sharp-fp8/upscales` HTTP API。
请求只包含 MP4 字节、受限输出边长和 seed，不能选择模型路径、Python、设备、工作目录或任意参数。
默认实现固定使用 `seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors` 与 FP16 VAE；当前 16 GB 开发显卡启用
CPU offload、block swap 和 VAE tiling。输出短边由请求给出（720 / 1080 / 1440），长边上限 1280 / 1920 / 2560。
SeedVR2 只写视频轨且保持帧数与帧率；worker 随后用 ffmpeg 把原视频的音轨（对白、音效）以 stream copy
封装回输出，视频流不重编码，原视频没有音轨时输出也没有。

SeedVR2 使用独立常驻 worker。相邻超分任务复用其模型缓存；切换到 H3 或 Breeze、任务取消、
Core 控制租约释放或服务关闭时，由同一个 `exclusive_gpu` 调度器退出 worker 并释放显存。该部署策略不会
出现在 Core 的项目 schema 或其它用户 Provider 的接口中。

当前 runtime 使用 Apache-2.0 的 [itontonpi/seedvr2](https://github.com/itontonpi/seedvr2) 作为外部部署依赖；
Sharp FP8 与 VAE 优先从 [ModelScope 镜像](https://www.modelscope.cn/models/numz/SeedVR2_comfyUI) 下载，不把
第三方代码或权重提交到本仓库。

### YuE2 Runtime

`yue2` 服务实现 `/yue2/generations` 的提交、状态、`/abort` 与 `/audio/{id}` 产物读取。请求只接受风格描述（1–1000 字）、
歌词（≤ 4000 字，可空即纯音乐）与 63 位 seed，拒绝未声明字段；内部乐谱模式固定 `cot=full`（带和弦 ABC 乐谱），
CFG、采样参数、ODE 步数与解码器沿用官方默认，不接受乐谱、模型路径或设备参数。

`yue2_worker.py` 在 WSL Ubuntu 的 `/home/ljx/ai/yue2/.venv`（Python 3.12、torch 2.10.0+cu128、`yue2_infer` 0.1.5）中
一次性运行：从 `/home/ljx/ai/models/YuE2-3B` 与 `/home/ljx/ai/models/YuE2-Vae` 离线加载（权重来自 ModelScope
`m-a-p/YuE2-3B`、`m-a-p/YuE2-Vae`，部署时校验 SHA-256），依次写内部乐谱、生成 25 Hz 语义 token、合成声学 latent、
分块解码，输出 48 kHz 立体声 16-bit PCM WAV 后退出并释放显存。乐谱等中间产物不回传。歌曲长度由歌词决定，
语义 token 上限 9000（约 6 分钟），达到上限时完成摘要注明被截断。不在任务期间安装依赖或下载模型；
GPU 或依赖失败直接返回任务错误。

歌词为空（纯音乐）时按官方纯音乐流程处理：模型乐谱固定分 `Vocal` 与 `Ins` 两个声部，即使风格写明无人声，
也常把主旋律写进 `Vocal`，生成时会被唱出来。worker 先用只有段落标签的写谱歌词（`[Intro]`、`[Verse]`、`[Chorus]`、
`[Outro]`）让模型写谱，乐谱为空或被截断时任务失败；再调用 `yue2_instrumental/` 中官方原样的 `convert_score`，把 `Vocal`
音符全部移到 `Ins`（重叠时人声优先，`Vocal` 只留休止与和弦，校验音高、时值、拍号、速度与和弦不变）；最后以改后乐谱作为
外部乐谱生成，歌词只填乐谱中的段落标签，有和弦用 `cot=full`、否则 `melody`。有歌词时只写一次谱、不改谱。
纯音乐没有歌词约束长度，慢速风格常写出超过 6 分钟生成上限的乐谱、生成被截断而没有结尾。改谱后按 `M:`/`Q:` 与时值
计算记谱时长，超过 300 秒时保留首段与末段，从末段之前逐段删去整段重复，直到不超过 300 秒；不删含调号、拍号或速度
变化的段，删后仍须通过官方解析器（连音不跨入不同音高或休止），完成摘要写明原长、删去的段与删后时长。
这样把有无人声从提示词服从度变成生成前的乐谱事实，但模型仍不保证绝对无人声。

### Qwen Image Runtime

`qwen_image` 服务实现 `/qwen-image/renders` 的提交、状态、`/cancel` 与 `/image/{id}` 产物读取。请求只接受
提示词、负向提示词、32 网格内 256–2048 的宽高、4–60 步、1–8 的 CFG、seed 与最多 5 张 PNG/JPEG/WebP 输入图，
拒绝未声明字段。输入图写进任务目录，`qwen_image_request.py` 只解析任务目录内的文件名。

`comfy_core/qwen_image.py` 在独立的最小 Comfy Core 子进程里执行固定图：只加载 ComfyUI 内置的
`nodes_qwen.py`，不扫描 custom nodes。模型固定为 `qwen\NoctQ_V4_int8_convrot.safetensors`、
`qwen\qwen3vl_8b_int8_convrot.safetensors` 与 `qwen\qwen_image_2.1_vae_bf16.safetensors`；输入图按顺序进入
`TextEncodeQwenImage21` 的 `image_N`（参考图像素预算 1024），画布由 `EmptyLatentImage` 的宽高决定，
采样器固定 euler / simple，KV cache 用 auto / default。相邻 Qwen 任务复用进程；与 H3、SeedVR2 等其它模型族
切换时由 `exclusive_gpu` 调度器释放。完成消息附带画布、输入图数、步数、CFG 与 seed 摘要；OOM 映射为明确错误，
不自动降档。

## Mac Codex / AGY image

Slatehand 自己的 `.venv` 安装 `codex` optional dependency 后执行：

```text
default_model_providers_implement/macos/install_launch_agent.sh
```

LaunchAgent 名为 `com.slatehand.codex-image`，只监听 `127.0.0.1:8792`，启用
`codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit,demucs_audio_separation`。图片生成与编辑是独立 HTTP 用法：`/codex/image-generations` 和 `/agy/image-generations` 接受零到五张
辅助参考并重新生成构图；`/codex/image-edits` 和 `/agy/image-edits` 要求一张不可省略的底图，并最多接受四张附加参考。Codex
worker 使用 read-only sandbox 和 ephemeral thread；编辑模式明确要求保留底图中未被修改的空间结构。
两种请求都必须声明 `aspect_ratio`，且只接受 `"16:9"`、`"9:16"` 或 `"2:1"`。返回的 `imageGeneration` 输出必须位于任务目录或管理员配置的
Codex 输出根目录，随后保留原图内最大的精确目标画幅区域并规范化为 PNG，不主动固定或降低像素尺寸。

AGY 路由使用同一严格请求形状和任务生命周期，但由已安装并完成用户认证的 `agy` CLI 执行。worker 为每个任务写入临时 custom agent，只开放 `generate_image` 与 `finish`，排除默认组件，不开放 shell、项目 MCP 或任意文件编辑。AGY 返回路径只接受任务目录或 `SLATEHAND_AGY_OUTPUT_ROOT`（默认原生 AGY brain 目录）中的本轮新文件；图片解码校验后同样裁切为准确画幅并规范化为 PNG。若图片工具已经产出合格文件，但其后的模型响应因容量等原因失败，worker 保留已完成图片，不重复提交生成。

Mac 启动脚本把本机能力拆成两个调度 lane：`network_image`（`codex_image_generate`、`codex_image_edit`、
`agy_image_generate`、`agy_image_edit`，4 并发）和 `mac_heavy`（`demucs_audio_separation`，互斥）。
已经就绪且彼此无依赖的图片任务可以并行，lane 之间互不等待。成片装配、Animatic、抽帧、全景取景与音轨重混
是 Core 本机工具（`core/media_tools/`），不经过本服务。这个并发开关不得用于 H3、Breeze 或 SeedVR2 等常驻 runtime；资源管理器会
拒绝为带 `release()` 的 runner 启用多 worker。Mac 服务不参与 Windows `exclusive_gpu`。

### lane 与排队提示

`--lane NAME:MAX:svc1,svc2` 可在同一个服务进程内声明多个调度 lane，参数可以重复给出。给出 `--lane` 时
不能再同时给 `--resource-name` 或 `--max-concurrent-tasks`，并且所有 lane 的服务并集必须精确等于
`--services`；未在 `--services` 中启用的服务、重复占有同一服务或格式错误都会直接退出。lane 内部沿用
原有的 FIFO 与并发上限，lane 之间互不等待；`revoke`（Core 租约释放或心跳超时）只取消本 lane 的任务并
只释放本 lane 的驻留 runtime，不影响其它 lane。不传 `--lane` 时服务只构造一个以 `--resource-name`
命名的 lane，Windows 启动行为完全不变。

排队中的任务在状态响应里返回 `排队中：即将开始。`（前面没有任务）或 `排队中：前面还有 N 个任务。`。
它只在生成响应时作为临时副本替换 `message`，不写回任务状态文件；这只是私有默认实现给用户看的进度
文案，会经插件的 `observe` 展示，不属于 Core Provider 协议，Core 不解析它。

### Mac 视频音轨分离

首次使用前执行 `default_model_providers_implement/macos/install_demucs.sh`，它只在仓库忽略的
`.demucs-venv/` 安装 Demucs 4 与 PyTorch。模型权重由 PyTorch 缓存管理，不进入仓库或 Core 协议。
`/demucs/audio-separations` 接受 MP4 字节和固定的 `voice` / `background` stem；worker 用 FFmpeg
提取 44.1 kHz 双声道音频，在本机 CPU/MPS 可用环境运行 `htdemucs`，并用标准 16-bit PCM 写回 WAV，
不依赖 TorchCodec。`background` 是 no-vocals residual，包含音乐、环境声与音效。

worker 只读任务目录中的固定文件名，取消由外层任务进程边界完成。

## 持久化与恢复

默认实现自己的 `runtime-state.json` 是模型调用执行状态，不是 Slatehand 项目事实。每次状态更新原子
替换文件；重启时：

- 已有完整 Artifact 的 running 调用转为 succeeded；
- 没有 Artifact 的 running 调用转为可重试的 failed，避免服务重启后静默重放重任务；
- queued 调用重新进入唯一资源队列；
- terminal 调用保持不变。

启用 Core 租约的 Windows 部署在新租约建立前不会恢复 queued 调用；租约被主动释放或超时撤销时，相关
未完成调用会成为 cancelled，而不是在没有 Core 的情况下继续占用 GPU。

Core 的 `project.json` 只保存插件翻译后、项目恢复所需的观察；不会读取该私有状态文件。

## 私有图片服务安装边界

Core 的 CodexImageProvider 与 AgyImageProvider 都只调用 HTTP，不安装 Agent SDK/CLI。私有 `codex_worker.py` 的生图执行需要 Codex SDK/Pillow：Mac 上安装本仓库 `.[services]` 时已包含，默认用服务自身的 `.venv` 运行；也可在独立环境中执行 `pip install -r default_model_providers_implement/requirements-codex-image.txt`，再用 `SLATEHAND_CODEX_PYTHON` 指向该环境的 Python。`agy_worker.py` 另要求宿主 PATH 中存在已认证的 `agy`。这是保留的媒体 Provider 实现，不是 Director/Compiler Agent runtime；用户外部 Agent 的安装与认证不受影响。
