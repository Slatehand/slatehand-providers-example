"""把 CodexImageProvider 安装为全局可绑定的插件实例。"""

from __future__ import annotations

from pathlib import Path

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST, SKILL
from .prompt_lint import lint_codex_image_prompt
from .provider import CodexImageProvider


def skill_resources() -> list[dict[str, str]]:
    directory = Path(__file__).parent / "skills" / SKILL
    return [
        {"name": "SKILL.md", "text": (directory / "SKILL.md").read_text(encoding="utf-8")},
    ]


def prompt_skills() -> list[dict]:
    """随插件发布的 Codex 图片提示词 Skill，由 Core 经专业契约与 Playground 交付。"""
    return [{"name": SKILL, "resources": skill_resources()}]


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = CodexImageProvider(endpoint, transport)
    return PluginInstance(
        MANIFEST,
        endpoint=endpoint,
        recipes={recipe.id: provider for recipe in MANIFEST.recipes},
        prompt_skills=prompt_skills,
        prompt_linter=lint_codex_image_prompt,
    )
