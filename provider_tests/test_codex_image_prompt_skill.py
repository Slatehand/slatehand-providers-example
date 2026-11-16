"""Codex 图片插件随附的提示词 Skill 与非阻塞软检查器。"""

import pytest
from core.director_proposals.professional_contracts import read_contract
from core.model_providers.image_prompt_skill import image_prompt_guide
from core.model_providers.manifest import Capability
from core.model_providers.registry import ProviderRegistry

from slatehand_providers.plugins.codex_image.manifest import MANIFEST, SKILL
from slatehand_providers.plugins.codex_image.plugin import plugin_instance, skill_resources
from slatehand_providers.plugins.codex_image.prompt_lint import lint_codex_image_prompt


def _catalog() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.install(plugin_instance(endpoint="http://127.0.0.1:8788"))
    registry.bind(Capability.IMAGE_GENERATE, "codex_image")
    registry.bind(Capability.IMAGE_EDIT, "codex_image")
    return registry


def test_codex_image_delivers_skill_to_keyframe_location_and_playground():
    catalog = _catalog()
    for recipe in MANIFEST.recipes:
        assert recipe.skills == (SKILL,)

    for capability in ("keyframe", "location"):
        resources = {
            item["name"]: item["text"]
            for item in read_contract(capability, provider_catalog=catalog)["resources"]
        }
        assert f"plugin/{SKILL}/SKILL.md" in resources
        skill = resources[f"plugin/{SKILL}/SKILL.md"]
        for required in (
            "≤ 850 字",
            "正交剥离",
            "50mm 标准定焦",
            "codex_image.generate",
            "codex_image.edit",
            "不叠括号结构禁令",
        ):
            assert required in skill, required
        for forbidden in (
            "将发未发",
            "蓄势",
            "蓄力",
            "动作即将发生",
            "动势",
            "environment_view_id",
            "为场景基础，保留",
            "reply_markdown",
        ):
            assert forbidden not in skill, forbidden

    playground_guide = image_prompt_guide(catalog, skill_text=True)
    assert [item["name"] for item in playground_guide["plugin_skills"]] == [SKILL]
    assert (
        playground_guide["plugin_skills"][0]["resources"][0]["text"] == skill_resources()[0]["text"]
    )


def test_codex_image_linter_accepts_clean_prompt_and_flags_anti_patterns():
    catalog = _catalog()
    clean = (
        "<Picture1>: 身份与服装参考。只取成年男性的五官与深灰粗布短褐；不采用图中的孩童与浅灰底。\n"
        "<Picture2>: 环境材质参考。只取青砖门洞质感与阴天冷灰天光；不采用图中的火光浓烟。\n\n"
        "画面正文：\n"
        "实拍电影静帧，50mm 标准定焦，低饱和冷灰自然色调。平视中近景，"
        "成年男性位于画面右侧三分之一处，腰部以上入画，继承<Picture1>的五官与深灰短褐，"
        "侧身立于<Picture2>质感的青砖门洞内侧，右手按在闭合的木门栓上，目光望向门缝外。"
        "阴天漫射冷光斜照在右侧颧骨。画面中无孩童、无明火、无字幕水印。"
    )
    assert (
        catalog.lint_prompt(
            Capability.IMAGE_GENERATE,
            "codex_image.generate",
            clean,
            {"asset_labels": ["<Picture1>", "<Picture2>"]},
        )
        == []
    )

    bloated = (
        "<Picture1>: 角色参考。\n\n"
        "画面正文：\n"
        + "实拍电影静帧，人物保持<Picture1>外观站在街口（严禁缺失手臂，绝无扭曲变形）！"
        + "背景细节丰富，" * 130
    )
    problems = lint_codex_image_prompt(
        "codex_image.generate",
        bloated,
        {"asset_labels": ["<Picture1>", "<Picture2>"]},
    )
    joined = "\n".join(problems)
    assert "偏长" in joined
    assert "感叹号" in joined
    assert "括号否定补丁" in joined
    assert "<Picture1>、<Picture2>" in joined

    # 前置依赖尚未生成时只检查文本自身反模式，不误报输入标签缺失。
    unready = lint_codex_image_prompt(
        "codex_image.edit",
        "保留原画面，仅将门扇改为半开（绝无扭曲变形）！",
        {"asset_labels": [], "inputs_ready": False},
    )
    assert any("感叹号" in item for item in unready)
    assert any("括号否定补丁" in item for item in unready)
    assert not any("输入标签" in item or "没有实际参考图" in item for item in unready)

    # 明确无参考图时出现 <Picture1> 给出软提示。
    stray = lint_codex_image_prompt(
        "codex_image.generate",
        "继承<Picture1>的青砖门洞质感，阴天冷光。",
        {"asset_labels": []},
    )
    assert any("没有实际参考图输入" in item for item in stray)


@pytest.mark.parametrize("length,flagged", [(850, False), (851, True)])
def test_codex_image_linter_matches_documented_length_guidance(length, flagged):
    problems = lint_codex_image_prompt("codex_image.generate", "画" * length, {})
    assert any("偏长" in item for item in problems) is flagged
