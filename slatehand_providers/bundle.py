"""作者自用默认部署的 Provider bundle：Mac 媒体服务、Windows 与 Colab GPU 节点。

部署配置来自 Provider 目录下的 ``provider.local.env`` 与 ``var/secrets/``（见 ``deployment``）。
安装顺序决定未显式绑定时的默认实现：Codex 先于 AGY 与 Qwen Image（生图/改图），
Stable Audio 3 先于 YuE2（文生音频），Breeze 先于 IndexTTS2.5（声音克隆）。
随 Core 启停的服务依次为：Colab 隧道、Mac LaunchAgent、Whisper。Windows 与 Colab 节点的启停
（以及 Windows 的活性心跳）由 scripts/windows_node.sh / colab_node.sh 手动管理，Core 只连接。
支持多个节点的插件由「运行节点」设置选择新提交的目标。
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
from slatehand_providers.plugins.nodes import route_plugin
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
    colab = deployment.colab
    colab_connection = (
        (colab.endpoint, UrllibTransport({"Authorization": "Bearer " + colab.token}))
        if colab is not None
        else None
    )

    def with_colab(factory, endpoint, transport=None, *, local="windows"):
        instances = {}
        if endpoint is not None:
            instances[local] = factory(endpoint, transport)
        if colab_connection is None:
            return instances[local]
        instances["colab"] = factory(*colab_connection)
        return route_plugin(instances, legacy_node=local)

    plugins = [
        codex_image_plugin(mac),
        agy_image_plugin(mac),
        with_colab(demucs_audio_plugin, mac, local="mac"),
    ]
    services = []
    if deployment.whisper_endpoint is not None or colab is not None:
        plugins.append(with_colab(whisper_asr_plugin, deployment.whisper_endpoint, local="mac"))
    else:
        print("未发现本机 Whisper ASR 与模型；Breeze 参考文字仍可手工填写。", flush=True)

    windows = deployment.windows
    if windows is not None or colab is not None:
        endpoint = windows.endpoint if windows is not None else None
        breeze_endpoint = windows.breeze_endpoint if windows is not None else None
        authorized = (
            UrllibTransport({"Authorization": "Bearer " + windows.token})
            if windows is not None
            else None
        )
        nodes = {"colab": colab_connection} if colab_connection is not None else {}
        plugins += [
            breeze_tts2_plugin(
                breeze_endpoint, context.runtime_directory / "breeze-tts2", authorized, nodes=nodes
            ),
            minimax_h3_plugin(
                endpoint,
                authorized,
                nodes=nodes,
                runtime_directory=context.runtime_directory / "h3-submissions",
            ),
            with_colab(seedvr2_plugin, endpoint, authorized),
            with_colab(stable_audio_3_plugin, endpoint, authorized),
            with_colab(yue2_plugin, endpoint, authorized),
            with_colab(qwen_image_plugin, endpoint, authorized),
            with_colab(indextts2_plugin, endpoint, authorized),
        ]
    if colab is not None:
        services.append(ColabTunnelService(colab))
    if deployment.mac_autostart and sys.platform == "darwin":
        services.append(MacProviderService(context.provider_directory / MAC_INSTALL_SCRIPT, mac))
    if deployment.whisper_server is not None and deployment.whisper_model is not None:
        services.append(WhisperService(deployment.whisper_server, deployment.whisper_model))
    return ProviderBundle(tuple(plugins), tuple(services))
