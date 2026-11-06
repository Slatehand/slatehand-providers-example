"""Provider 包只用 Core 的 Provider SDK 公共面；模型服务完全不依赖 Core。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Provider 包可以使用的 Core 模块：Provider SDK 与两个无状态工具。
SDK = (
    "core.model_providers.boundary",
    "core.model_providers.bundle",
    "core.model_providers.contracts",
    "core.model_providers.http",
    "core.model_providers.manifest",
    "core.model_providers.recipe",
    "core.model_providers.registry",
    "core.media_assets",
    "core.director_proposals.schema_gen",
    "core.director_proposals.compiler_intent",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _python_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" not in path.parts:
            yield path


def test_provider_plugins_use_only_the_sdk_surface() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in _python_files(ROOT / "slatehand_providers")
        for name in _imports(path)
        if name.split(".")[0] in {"core", "server", "integrations"}
        and not any(name == allowed or name.startswith(allowed + ".") for allowed in SDK)
    ]
    assert offenders == []


def test_model_services_stand_alone_without_core() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in _python_files(ROOT / "default_model_providers_implement")
        if "yue2_instrumental" not in path.parts
        for name in _imports(path)
        if name.split(".")[0] in {"core", "server", "integrations", "slatehand_providers"}
    ]
    assert offenders == []
