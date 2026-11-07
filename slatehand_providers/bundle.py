"""作者自用默认部署的 Provider bundle：Mac 媒体服务、本机 whisper.cpp 与 Windows GPU 节点。

部署配置来自 Provider 目录下的 ``provider.local.env`` 与 ``var/secrets/``（见 ``deployment``）。
安装顺序决定未显式绑定时的默认实现：Codex 先于 AGY 与 Qwen Image（生图/改图），
Stable Audio 3 先于 YuE2（文生音频），Breeze 先于 IndexTTS2.5（声音克隆）。
随 Core 启停的服务依次为：Colab 隧道、Mac LaunchAgent、Whisper。Windows 与 Colab 节点的启停
（以及 Windows 的活性心跳）由 scripts/windows_node.sh / colab_node.sh 手动管理，Core 只连接。
H3 与 Breeze 可同时接入 Windows 与 Colab 两个节点，由插件设置选择新提交的节点。
"""

from __future__ import annotations

import sys

from core.model_providers.bundle import BundleContext, ProviderBundle
from core.model_providers.http import UrllibTransport

from slatehand_providers.plugins.agy_image.plugin import plugin_instance as agy_image_plugin
from slatehand_providers.plugins.breeze_tts2.plugin import plugin_instance as breeze_tts2_plugin
from slatehand_providers.plugins.codex_image.plugin import plugin_instance as codex_image_plugin
from slatehand_providers.plugins.demucs_audio.plugin import plugin_instance as demucs_audio_plugin
from slatehand_providers.plugins.indextts2.plugin import plugin_instance as indextts2_plugin
from slatehand_providers.plugins.minimax_h3.plugin import plugin_instance as minimax_h3_plugin
from slatehand_providers.plugins.qwen_image.plugin import plugin_instance as qwen_image_plugin
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8.plugin import (
    plugin_instance as seedvr2_plugin,
)
from slatehand_providers.plugins.stable_audio_3.plugin import (
    plugin_instance as stable_audio_3_plugin,
)
from slatehand_providers.plugins.whisper_asr.plugin import plugin_instance as whisper_asr_plugin
from slatehand_providers.plugins.yue2.plugin import plugin_instance as yue2_plugin

from .colab_tunnel import ColabTunnelService
from .deployment import Deployment, read_deployment
from .services import MacProviderService, WhisperService

MAC_INSTALL_SCRIPT = "default_model_providers_implement/macos/install_launch_agent.sh"


def create_bundle(context: BundleContext) -> ProviderBundle:
    return build_bundle(read_deployment(context.provider_directory), context)


def build_bundle(deployment: Deployment, context: BundleContext) -> ProviderBundle:
    mac = deployment.mac_endpoint
    plugins = [
        codex_image_plugin(mac),
        agy_image_plugin(mac),
        demucs_audio_plugin(mac),
    ]
    services = []
    if deployment.whisper_endpoint is not None:
        plugins.append(whisper_asr_plugin(deployment.whisper_endpoint))
    else:
        print("未发现本机 Whisper ASR 与模型；Breeze 参考文字仍可手工填写。", flush=True)
    colab = deployment.colab
    gpu_nodes = {}
    if colab is not None:
        gpu_nodes["colab"] = (
            colab.endpoint,
            UrllibTransport({"Authorization": "Bearer " + colab.token}),
        )
    windows = deployment.windows
    if windows is not None:
        authorized = UrllibTransport({"Authorization": "Bearer " + windows.token})
        plugins.append(
            breeze_tts2_plugin(
                windows.breeze_endpoint,
                context.runtime_directory / "breeze-tts2",
                authorized,
                nodes=gpu_nodes,
            )
        )
        plugins += [
            minimax_h3_plugin(windows.endpoint, authorized, nodes=gpu_nodes),
            seedvr2_plugin(windows.endpoint, authorized),
            stable_audio_3_plugin(windows.endpoint, authorized),
            yue2_plugin(windows.endpoint, authorized),
            qwen_image_plugin(windows.endpoint, authorized),
            indextts2_plugin(windows.endpoint, authorized),
        ]
    if windows is None and colab is not None:
        plugins += [
            breeze_tts2_plugin(None, context.runtime_directory / "breeze-tts2", nodes=gpu_nodes),
            minimax_h3_plugin(nodes=gpu_nodes),
        ]
    if colab is not None:
        # Colab VM 由人手动开关（scripts/colab_node.sh）；这里只维持隧道，不启停、不租约。
        services.append(ColabTunnelService(colab))
    if deployment.mac_autostart and sys.platform == "darwin":
        services.append(MacProviderService(context.provider_directory / MAC_INSTALL_SCRIPT, mac))
    if deployment.whisper_server is not None and deployment.whisper_model is not None:
        services.append(WhisperService(deployment.whisper_server, deployment.whisper_model))
    return ProviderBundle(tuple(plugins), tuple(services))
