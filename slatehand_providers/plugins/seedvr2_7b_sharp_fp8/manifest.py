"""SeedVR2 7B Sharp FP8 插件 manifest：视频超分。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.media_assets import read_mp4_video_size
from core.model_providers.manifest import (
    Capability,
    Field,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    seed_field,
)

# 目标档位 → 输出短边。长边上限统一放宽到 2560，只防异常画幅，
# 不截断常规 16:9 / 9:16 / 2:1 的放大结果；最终装配再统一缩放裁切到交付画布。
TARGET_SHORT_SIDE = {"720p": 720, "1080p": 1080}
MAX_LONG_SIDE = 2560
# 原视频短边达到目标的这个比例即视为“已接近目标档位”，超分没有意义。
NEAR_TARGET_RATIO = 0.9


def check_upscale_input(inputs: Mapping[str, tuple[Any, ...]], settings: Mapping[str, Any]) -> None:
    """原视频短边已接近或超过目标档位时拒绝；读不出尺寸时交给模型服务处理。"""
    items = inputs.get("video", ())
    if not items:
        return
    size = read_mp4_video_size(items[0].content)
    if size is None:
        return
    tier = str(settings["resolution"])
    target = TARGET_SHORT_SIDE[tier]
    short_side = min(size)
    if short_side >= target * NEAR_TARGET_RATIO:
        raise ValueError(
            f"原视频为 {size[0]}×{size[1]}，短边 {short_side}px 已接近或超过目标档位 {tier}"
            f"（短边 {target}px），无需超分。需要更高清晰度时，请在 Provider 设置中把 SeedVR2 "
            "目标分辨率调到更高档位。"
        )


MANIFEST = PluginManifest(
    plugin_id="seedvr2_7b_sharp_fp8",
    plugin_version=1,
    label="SeedVR2 7B Sharp FP8",
    settings=(
        Field(
            "resolution",
            Widget.ENUM,
            "目标分辨率",
            default="1080p",
            options=(
                Option("720p", "720p（短边 720）"),
                Option("1080p", "1080p（短边 1080）"),
            ),
            summary=True,
            help="超分输出的短边。原视频短边已达到所选档位的 90% 时拒绝超分。",
        ),
    ),
    recipes=(
        Recipe(
            "seedvr2_7b_sharp_fp8.upscale",
            Capability.VIDEO_UPSCALE,
            "视频超分",
            slots=(
                Slot("video", Role.SOURCE_VIDEO, "来源视频", minimum=1, media_types=("video/mp4",)),
            ),
            # SeedVR2 内部用 numpy 风格的 32 位无符号 seed。
            params=(seed_field(maximum=2**32 - 1),),
            input_check=check_upscale_input,
        ),
    ),
)
