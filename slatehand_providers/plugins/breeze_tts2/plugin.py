"""把 Breeze-TTS-2 安装为全局可绑定的插件实例：同一实现承担音色设计与声音克隆。

可同时接入多个运行节点（本地 Windows、Colab），由实例设置 ``node`` 选择新提交的目标。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from slatehand_providers.plugins.nodes import DEFAULT_NODE, NodeRouter

from .manifest import MANIFEST
from .provider import BreezeTTS2Provider

BreezeNode = tuple[str, HttpTransport | None]


def plugin_instance(
    endpoint: str | None,
    spool_dir: Path,
    transport: HttpTransport | None = None,
    *,
    nodes: Mapping[str, BreezeNode] | None = None,
) -> PluginInstance:
    """``endpoint``/``transport`` 是默认节点；``nodes`` 追加其它节点（键见 ``NODE_LABELS``）。"""
    all_nodes: dict[str, BreezeNode] = {}
    if endpoint is not None:
        all_nodes[DEFAULT_NODE] = (endpoint, transport)
    all_nodes.update(nodes or {})
    if not all_nodes:
        raise ValueError("Breeze 插件至少需要一个运行节点。")
    router = NodeRouter(
        "Breeze-TTS-2",
        {
            key: BreezeTTS2Provider(node_endpoint, spool_dir, node_transport)
            for key, (node_endpoint, node_transport) in all_nodes.items()
        },
    )
    return PluginInstance(
        MANIFEST,
        recipes={"breeze_tts2.voice_design": router, "breeze_tts2.clone": router},
        endpoint=next(iter(all_nodes.values()))[0],
    )
