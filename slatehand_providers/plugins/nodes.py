"""运行节点路由（H3、Breeze 共用）：一个插件可同时接入多个部署节点，按设置 ``node`` 选提交目标。

切换节点只影响新提交。句柄记住提交时的节点，之后的 observe/cancel/read_artifact 回到原节点，
因此切换不会打断已在运行的任务。默认节点（本地 Windows）的句柄保持原始 job token，与切换前
已持久化的句柄兼容；其它节点在 token 前加 ``<node>:`` 前缀。
"""

from __future__ import annotations

from collections.abc import Mapping

from core.model_providers.boundary import (
    GenerationObservation,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.manifest import Field, Option, Widget

DEFAULT_NODE = "windows"
NODE_LABELS = {"windows": "本地 Windows", "colab": "Colab G4"}


def node_setting() -> Field:
    """插件实例设置「运行节点」：只影响新提交；运行中的任务按句柄回到提交时的节点。"""
    return Field(
        "node",
        Widget.ENUM,
        "运行节点",
        default=DEFAULT_NODE,
        options=tuple(Option(key, label) for key, label in NODE_LABELS.items()),
        summary=True,
    )


class NodeRouter:
    """包装同一 recipe 在各节点上的实现；对 Core 表现为单一实现。"""

    def __init__(self, label: str, providers: Mapping[str, object]) -> None:
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

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def submit_recipe(self, request) -> ProviderHandle:
        node = dict(request.settings).get("node", DEFAULT_NODE)
        provider = self._provider(node)
        handle = provider.submit_recipe(request)
        if node == DEFAULT_NODE:
            return handle
        return ProviderHandle(
            handle.plugin_id, handle.plugin_version, f"{node}:{handle.external_id}"
        )

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
        if not separator or node not in NODE_LABELS or node == DEFAULT_NODE:
            return self._provider(DEFAULT_NODE), handle
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
