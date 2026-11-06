"""YuE2-3B 插件 manifest：由风格描述与歌词生成整首歌。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    Field,
    PluginManifest,
    Recipe,
    Widget,
    prompt_field,
    seed_field,
)

SKILL = "yue2-song-writing"
STYLE_MAX_LENGTH = 1000
LYRICS_MAX_LENGTH = 4000

MANIFEST = PluginManifest(
    plugin_id="yue2",
    plugin_version=1,
    label="YuE2-3B",
    recipes=(
        Recipe(
            "yue2.generate",
            Capability.AUDIO_GENERATE,
            "歌曲生成",
            params=(
                prompt_field(STYLE_MAX_LENGTH, "风格描述"),
                Field(
                    "lyrics",
                    Widget.PROMPT,
                    "歌词",
                    default="",
                    max_length=LYRICS_MAX_LENGTH,
                    help=(
                        "用 [Verse]、[Chorus] 等段落标签分段；留空生成纯音乐。歌曲长度由歌词决定。"
                    ),
                ),
                seed_field(),
            ),
            skills=(SKILL,),
        ),
    ),
)
