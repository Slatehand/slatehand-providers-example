"""HunyuanVideo-Foley XXL：从来源视频和声音描述生成同步音效。"""

from core.model_providers.manifest import (
    Capability,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    prompt_field,
    seed_field,
)

MANIFEST = PluginManifest(
    plugin_id="hunyuan_foley",
    plugin_version=1,
    label="HunyuanVideo-Foley XXL",
    recipes=(
        Recipe(
            "hunyuan_foley.generate",
            Capability.AUDIO_FOLEY,
            "视频音效",
            slots=(
                Slot(
                    "video",
                    Role.SOURCE_VIDEO,
                    "来源视频",
                    minimum=1,
                    media_types=("video/mp4",),
                    duration_seconds=(1, 15),
                ),
            ),
            params=(prompt_field(1000, "音效描述"), seed_field()),
        ),
    ),
)
