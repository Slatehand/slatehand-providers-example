"""H3 插件设置：预设绑定基础模型与步数，分辨率档位换算到 32 像素网格画布。"""

from slatehand_providers.plugins.minimax_h3 import MANIFEST as H3_MANIFEST
from slatehand_providers.plugins.minimax_h3 import render_settings
from slatehand_providers.plugins.minimax_h3.render import H3RenderSettings, H3Resolution


def test_h3_preset_binds_base_model_and_steps() -> None:
    assert render_settings(H3_MANIFEST.default_settings()) == H3RenderSettings()
    turbo = {**H3_MANIFEST.default_settings(), "preset": "turbo_v2", "resolution": "1080p"}
    assert render_settings(turbo) == H3RenderSettings(H3Resolution.P1080, 8, True, True)
    assert H3_MANIFEST.settings_summary(turbo) == (
        "Turbo V2 · 8 步 · 1080p · Sage · SelfLift · 本地 Windows"
    )
    assert H3_MANIFEST.hint("soft_duration_limit_seconds") == 15


def test_official_pruned_bf16_preset_is_twenty_steps_with_its_own_base_model() -> None:
    official = {**H3_MANIFEST.default_settings(), "preset": "official_pruned_bf16"}
    render = render_settings(official)
    assert (render.steps, render.base_model) == (20, "official_pruned_bf16")
    assert render_settings(H3_MANIFEST.default_settings()).base_model == "dasiwa_hybrid_v2"
    assert H3RenderSettings.from_json(render.to_json()) == render
    assert H3_MANIFEST.settings_summary(official).startswith("官方 Pruned BF16 · 20 步")


def test_h3_render_canvas_tiers_follow_the_32_pixel_grid() -> None:
    expected = {
        H3Resolution.P480: (864, 480),
        H3Resolution.P720: (1280, 704),
        H3Resolution.P1080: (1920, 1088),
    }
    for resolution, (width, height) in expected.items():
        settings = H3RenderSettings(resolution)
        assert settings.canvas("16:9") == (width, height)
        assert settings.canvas("9:16") == (height, width)
        assert (width % 32, height % 32) == (0, 0)
    wide = {
        H3Resolution.P480: (960, 480),
        H3Resolution.P720: (1408, 704),
        H3Resolution.P1080: (1920, 960),
    }
    for resolution, (width, height) in wide.items():
        assert H3RenderSettings(resolution).canvas("2:1") == (width, height)
        assert (width % 32, height % 32) == (0, 0)
