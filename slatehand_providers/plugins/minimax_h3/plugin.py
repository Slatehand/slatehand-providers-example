"""把 MiniMax H3 安装为全局可绑定的插件实例：FL2VA 与 Ref2VA 两个 recipe 各有实现。

可同时接入多个运行节点（本地 Windows、Colab），由实例设置 ``node`` 选择新提交的目标。
"""

from __future__ import annotations

from collections.abc import Mapping

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from slatehand_providers.plugins.minimax_h3.fl2va import MiniMaxH3FL2VAProvider
from slatehand_providers.plugins.minimax_h3.ref2va import MiniMaxH3Ref2VAProvider
from slatehand_providers.plugins.nodes import DEFAULT_NODE, NodeRouter

from .manifest import MANIFEST
from .prompt_context import format_prompt_workset, prompt_skills
from .prompt_lint import lint_h3_prompt

H3Node = tuple[str, HttpTransport | None]


def plugin_instance(
    endpoint: str | None = None,
    transport: HttpTransport | None = None,
    *,
    nodes: Mapping[str, H3Node] | None = None,
) -> PluginInstance:
    """``endpoint``/``transport`` 是默认节点；``nodes`` 追加其它节点（键见 ``NODE_LABELS``）。"""
    all_nodes: dict[str, H3Node] = {}
    if endpoint is not None:
        all_nodes[DEFAULT_NODE] = (endpoint, transport)
    all_nodes.update(nodes or {})
    if not all_nodes:
        raise ValueError("H3 插件至少需要一个运行节点。")
    return PluginInstance(
        MANIFEST,
        endpoint=next(iter(all_nodes.values()))[0],
        prompt_formatter=format_prompt_workset,
        prompt_skills=prompt_skills,
        prompt_linter=lint_h3_prompt,
        recipes={
            "minimax_h3.fl2va": NodeRouter(
                "H3 FL2VA",
                {key: MiniMaxH3FL2VAProvider(*node) for key, node in all_nodes.items()},
            ),
            "minimax_h3.ref2va": NodeRouter(
                "H3 Ref2VA",
                {key: MiniMaxH3Ref2VAProvider(*node) for key, node in all_nodes.items()},
            ),
        },
    )
