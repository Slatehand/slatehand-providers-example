"""运行节点路由：一个插件可同时接入多个部署节点，按设置 ``node`` 选提交目标。

切换节点只影响新提交。句柄记住提交时的节点，之后的 observe/cancel/read_artifact 回到原节点，
因此切换不会打断已在运行的任务。原有本机节点的句柄保持原始 job token，与切换前
已持久化的句柄兼容；其它节点在 token 前加 ``<node>:`` 前缀。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from core.model_providers.boundary import (
    GenerationObservation,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.manifest import Field, Option, PluginManifest, Widget
from core.model_providers.registry import PluginInstance

DEFAULT_NODE = "windows"
NODE_LABELS = {"windows": "本地 Windows", "colab": "Colab G4", "mac": "本地 Mac"}


def node_setting(*nodes: str, default: str = DEFAULT_NODE) -> Field:
    """插件实例设置「运行节点」：只影响新提交；运行中的任务按句柄回到提交时的节点。"""
    return Field(
        "node",
        Widget.ENUM,
        "运行节点",
        default=default,
        options=tuple(Option(key, NODE_LABELS[key]) for key in (nodes or ("windows", "colab"))),
        summary=True,
    )


class NodeRouter:
    """包装同一 recipe 在各节点上的实现；对 Core 表现为单一实现。"""

    def __init__(
        self, label: str, providers: Mapping[str, object], *, legacy_node: str = DEFAULT_NODE
    ) -> None:
        if not providers:
            raise ValueError(f"{label} 至少需要一个运行节点。")
        unknown = set(providers) - set(NODE_LABELS)
        if unknown:
            raise ValueError(f"未知运行节点：{', '.join(sorted(unknown))}")
        identities = {(p.plugin_id, p.plugin_version) for p in providers.values()}  # type: ignore[attr-defined]
        if len(identities) != 1:
            raise ValueError("各节点的实现必须是同一插件版本。")
        ((self.plugin_id, self.plugin_version),) = identities
        self._label = label
        self._providers = dict(providers)
        self._legacy_node = legacy_node
        self._default_node = legacy_node if legacy_node in providers else next(iter(providers))

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def submit_recipe(self, request) -> ProviderHandle:
        node = dict(request.settings).get("node", self._default_node)
        provider = self._provider(node)
        handle = provider.submit_recipe(request)
        if node == self._legacy_node:
            return handle
        return ProviderHandle(
            handle.plugin_id, handle.plugin_version, f"{node}:{handle.external_id}"
        )

    def execute_recipe(self, request):
        node = dict(request.settings).get("node", self._default_node)
        return self._provider(node).execute_recipe(request)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        provider, inner = self._route(handle)
        return provider.observe(inner)

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        provider, inner = self._route(handle)
        return provider.cancel(inner)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        provider, inner = self._route(handle)
        return provider.read_artifact(inner, artifact_id)

    def _route(self, handle: ProviderHandle) -> tuple[object, ProviderHandle]:
        node, separator, token = handle.external_id.partition(":")
        if not separator or node not in NODE_LABELS or node == self._legacy_node:
            return self._provider(self._legacy_node), handle
        return self._provider(node), ProviderHandle(handle.plugin_id, handle.plugin_version, token)

    def _provider(self, node: str):
        provider = self._providers.get(node)
        if provider is None:
            label = NODE_LABELS.get(node, node)
            raise ModelProviderError(
                "node_unavailable",
                f"{self._label} 运行节点「{label}」未在本机部署配置中接入；"
                "请在 Provider 设置里换节点。",
            )
        return provider


def manifest_for_nodes(
    manifest: PluginManifest, nodes: tuple[str, ...], *, legacy_node: str = DEFAULT_NODE
) -> PluginManifest:
    default = legacy_node if legacy_node in nodes else nodes[0]
    allowed = (legacy_node, "colab")
    field = node_setting(*allowed, default=default)
    settings = manifest.settings
    if any(item.key == "node" for item in settings):
        settings = tuple(field if item.key == "node" else item for item in settings)
    else:
        settings = (*settings, field)
    return replace(manifest, settings=settings)


def route_plugin(
    instances: Mapping[str, PluginInstance], *, legacy_node: str = DEFAULT_NODE
) -> PluginInstance:
    first = next(iter(instances.values()))
    return replace(
        first,
        manifest=manifest_for_nodes(first.manifest, tuple(instances), legacy_node=legacy_node),
        recipes={
            recipe_id: NodeRouter(
                first.manifest.label,
                {node: plugin.recipes[recipe_id] for node, plugin in instances.items()},
                legacy_node=legacy_node,
            )
            for recipe_id in first.recipes
        },
    )
