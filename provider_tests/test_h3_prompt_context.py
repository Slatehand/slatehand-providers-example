"""H3 插件：从 Core 视频工作集推导 H3 提示词上下文（模式、描述与校验）。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from slatehand_providers.plugins.minimax_h3.prompt_context import context_from_workset
from slatehand_providers.plugins.minimax_h3.prompt_contract import H3PromptMode


def _workset(
    *,
    recipe_id: str = "minimax_h3.ref2va",
    start: str | None = "首帧画面。",
    end: str | None = "尾帧画面。",
    bindings: tuple[dict, ...] = (),
    dialogue: tuple[dict, ...] = (),
) -> dict:
    return {
        "context": {
            "recipe_id": recipe_id,
            "duration_seconds": 6.0,
            "aspect_ratio": "16:9",
            "scene": {"title": "雨夜", "setting": "车站", "driver": "drama"},
            "shots": [
                {
                    "composition": "中景",
                    "camera_movement": "固定",
                    "action": "甲转身。",
                    "audio_direction": "雨声。",
                    "visible_character_names": ["甲"],
                }
            ],
            "segment": {
                "action": "甲转身看向乙。",
                "historical_prompt": "",
                "continues_from_previous_segment": False,
                "continues_into_next_segment": False,
                "start_frame_description": start,
                "end_frame_description": end,
                "dialogue": list(dialogue),
            },
            "bindings": list(bindings),
        }
    }


def _binding(role: str, description: str) -> dict:
    return {"role": role, "description": description, "label": None, "asset_id": "a" * 32}


@pytest.mark.parametrize(
    ("recipe_id", "start", "end", "mode"),
    [
        ("minimax_h3.ref2va", "首帧。", "尾帧。", H3PromptMode.REF2VA),
        ("minimax_h3.ref2va", None, None, H3PromptMode.REF2VA),
        ("minimax_h3.fl2va", "首帧。", "尾帧。", H3PromptMode.FL2VA),
        ("minimax_h3.fl2va", "首帧。", None, H3PromptMode.I2VA),
        ("minimax_h3.fl2va", None, "尾帧。", H3PromptMode.L2VA),
        ("minimax_h3.fl2va", None, None, H3PromptMode.T2VA),
    ],
)
def test_mode_follows_recipe_and_enabled_frames(recipe_id, start, end, mode) -> None:
    context = context_from_workset(_workset(recipe_id=recipe_id, start=start, end=end))
    assert context.mode is mode
    assert context.start_frame_description == start
    assert context.end_frame_description == end


def test_reference_descriptions_follow_binding_roles() -> None:
    context = context_from_workset(
        _workset(
            start=None,
            end=None,
            bindings=(
                _binding("reference_audio", "原样使用这段对白。"),
                _binding("reference_image", "红色行李箱。"),
            ),
        )
    )
    assert context.mode is H3PromptMode.REF2VA
    assert context.audio_reference_descriptions == ("原样使用这段对白。",)
    assert context.additional_image_descriptions == ("红色行李箱。",)
    assert context.video_reference_descriptions == ()
    assert not context.dialogue


def test_context_rejects_invalid_video_reference_descriptions() -> None:
    context = context_from_workset(_workset())
    with pytest.raises(ValueError, match="多于 3 项"):
        replace(context, video_reference_descriptions=("参考。",) * 4)
    with pytest.raises(ValueError, match="不能为空"):
        replace(context, video_reference_descriptions=("  ",))
    with pytest.raises(ValueError, match="不能为空"):
        replace(context, video_reference_descriptions=("长" * 2_001,))
    with pytest.raises(ValueError, match="参考视频只适用于 Ref2VA"):
        replace(
            context,
            mode=H3PromptMode.FL2VA,
            additional_image_descriptions=(),
            audio_reference_descriptions=(),
            video_reference_descriptions=("参考。",),
        )


def test_payload_without_scene_lists_single_shot_and_groups_provider_labels() -> None:
    from slatehand_providers.plugins.minimax_h3.prompt_contract import H3PromptContext, H3ShotInput
    from slatehand_providers.plugins.minimax_h3.prompt_payload import (
        _actual_provider_inputs,
        h3_prompt_payload,
    )

    context = H3PromptContext(
        mode=H3PromptMode.REF2VA,
        duration_seconds=8.0,
        aspect_ratio="16:9",
        scene_title="雨夜",
        scene_setting="街道",
        shots=(
            H3ShotInput(
                composition="中景",
                camera_movement="推近",
                action="等待",
                audio_direction="雨声",
                visible_character_names=("小满",),
            ),
        ),
        segment_action="上车",
        historical_prompt="",
        user_direction="",
        start_frame_description="首帧描述",
        end_frame_description="尾帧描述",
        dialogue=(),
        additional_image_descriptions=("角色正面", "道具特写"),
        audio_reference_descriptions=("音色参考", "对白"),
        video_reference_descriptions=("运镜参考",),
    )
    # Playground 没有 Scene，单 Shot 也走同一个 shots 列表。
    payload = h3_prompt_payload(context)
    assert payload["scene"]["driver"] is None
    assert payload["shots"] == [
        {
            "composition": "中景",
            "camera_movement": "推近",
            "action": "等待",
            "audio_direction": "雨声",
            "visible_character_names": ["小满"],
        }
    ]
    provider = _actual_provider_inputs(context)
    assert [item["label"] for item in provider["pictures"]] == [
        f"<Picture {index}>" for index in range(1, 5)
    ]
    assert [item["label"] for item in provider["audios"]] == ["<Audio 1>", "<Audio 2>"]
    assert [item["label"] for item in provider["videos"]] == ["<Video 1>"]
    assert provider["allowed_asset_reference_labels"] == [
        *(f"<Picture {index}>" for index in range(1, 5)),
        "<Audio 1>",
        "<Audio 2>",
        "<Video 1>",
    ]
