"""H3 插件随附的提示词 Skill：约束文本与工作集字段对得上。"""

from core.model_providers.manifest import Capability, DomainPredicate

from slatehand_providers.plugins.minimax_h3.manifest import MANIFEST
from slatehand_providers.plugins.minimax_h3.plugin import plugin_instance
from slatehand_providers.plugins.minimax_h3.prompt_context import skill_resources


def test_skill_covers_labels_subjects_cut_syntax_and_exclusions():
    skill = next(r["text"] for r in skill_resources() if r["name"] == "SKILL.md")
    assert "allowed_asset_reference_labels" in skill
    assert "Subject" in skill and "不是新的图片输入" in skill
    assert "MM:SS.mmm" in skill and "未要求的排除项不自动新增" in skill


def test_skill_explains_off_screen_speakers():
    text = "\n".join(r["text"] for r in skill_resources())
    assert "on_screen=false" in text


def test_skill_owns_voice_and_music_rules_for_projects():
    skill = next(r["text"] for r in skill_resources() if r["name"] == "SKILL.md")
    assert "预留后期主旁白音频叠加通道" in skill
    assert "主动清除历史画外音文本" in skill
    assert "non_diegetic_music" in skill and "N/A" in skill


def test_skill_defines_in_segment_cut_syntax():
    skill = next(r["text"] for r in skill_resources() if r["name"] == "SKILL.md")
    assert "<scenetrans>" in skill
    assert "[Shot" in skill


def test_h3_defaults_to_ref2va_and_skill_anchors_missing_or_partial_characters():
    plugin = plugin_instance(endpoint="http://127.0.0.1:8791")
    assert plugin.default_recipe(Capability.VIDEO_GENERATE, frozenset()).id == "minimax_h3.ref2va"
    assert (
        plugin.default_recipe(
            Capability.VIDEO_GENERATE, frozenset({DomainPredicate.SEGMENT_HAS_DIALOGUE})
        ).id
        == "minimax_h3.ref2va"
    )
    assert dict(MANIFEST.defaults)[Capability.VIDEO_GENERATE][0].recipe == "minimax_h3.ref2va"

    combined = "\n".join(r["text"] for r in skill_resources())
    for required in (
        "一律优先推荐与使用 `minimax_h3.ref2va`",
        "确实没必要用 Ref2VA",
        "character_visuals",
        "unanchored_characters",
        "首尾帧只有该角色的局部",
        "忽略设定图的浅灰背景与多视角排版",
        "reference generation",
    ):
        assert required in combined, required
    for stale in (
        "需要参考素材时先经用户同意切到 `minimax_h3.ref2va`",
        "只在用户明确要求时修改绑定",
    ):
        assert stale not in combined, stale
