"""H3 插件随附的提示词 Skill：约束文本与工作集字段对得上。"""

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
