"""把 YuE2Provider 安装为全局可绑定的插件实例。"""

from __future__ import annotations

from pathlib import Path

from core.model_providers.http import HttpTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST, SKILL
from .provider import YuE2Provider


def prompt_skills() -> list[dict]:
    """随插件发布的歌曲写作 Skill 正文，由 Playground 能力目录交付。"""
    path = Path(__file__).parent / "skills" / SKILL / "SKILL.md"
    return [{"name": SKILL, "resources": [{"name": "SKILL.md", "text": path.read_text("utf-8")}]}]


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    provider = YuE2Provider(endpoint, transport)
    return PluginInstance(
        MANIFEST,
        endpoint=endpoint,
        recipes={recipe.id: provider for recipe in MANIFEST.recipes},
        prompt_skills=prompt_skills,
    )
