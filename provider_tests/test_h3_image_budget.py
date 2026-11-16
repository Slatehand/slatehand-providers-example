"""H3 图片总预算在 Core 最终提交前执行；规划与输入簿仍可保存九张其他图片。"""

import asyncio

import pytest
from core.director_commands import DirectorCommand
from core.model_providers.manifest import Capability
from core.model_providers.registry import PluginInstance
from core.structured_director import ImageAssetCategory
from structured_director_fixtures import RecordingProvider
from test_prompt_worksets import fixture

from slatehand_providers.plugins.minimax_h3.manifest import MANIFEST


@pytest.mark.parametrize("start,end", [(False, False), (True, False), (False, True), (True, True)])
def test_core_checks_actual_image_total_before_generation_or_provider_call(tmp_path, start, end):
    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        provider = RecordingProvider(media_type="video/mp4", content=b"unused")
        service._registry.install(
            PluginInstance(MANIFEST, recipes={recipe.id: provider for recipe in MANIFEST.recipes})
        )
        service._registry.bind(Capability.VIDEO_GENERATE, MANIFEST.plugin_id)
        segment_id = doc.video_plan.segments[0].segment_id
        doc = await service.save_segment_video_recipe(
            segment_id=segment_id, recipe_id="minimax_h3.ref2va", expected_revision=doc.revision
        )
        doc = service._command_registry.execute(
            DirectorCommand(
                "keyframe.apply_operations",
                doc.revision,
                "image-budget-activation",
                {
                    "operations": [
                        {
                            "op": "set_activation",
                            "segment_id": segment_id,
                            "start_enabled": start,
                            "end_enabled": end,
                        }
                    ]
                },
            )
        ).document
        references = []
        for index in range(9):
            doc = await service.import_image_asset(
                media_type="image/png",
                content=b"\x89PNG\r\n\x1a\nbudget" + bytes([index]),
                category=ImageAssetCategory.KEYFRAME,
                expected_revision=doc.revision,
            )
            references.append({"asset_id": doc.assets[-1].id, "description": f"参考图 {index + 1}"})
        # 即使有首尾帧，九张其他图片仍可保存；最终按实际提交的图片检查预算。
        doc = await service.save_segment_video_inputs(
            segment_id=segment_id,
            prompt_text="角色保持原位。",
            bindings={"additional_images": references},
            params={},
            expected_revision=doc.revision,
        )
        if start or end:
            before = store.path.read_bytes()
            with pytest.raises(ValueError, match="首尾帧与参考图.*不能超过 9 张"):
                await service._media.generate_segment_video(
                    segment_id=segment_id, expected_revision=doc.revision
                )
            assert store.path.read_bytes() == before
            assert provider.requests == []
            if start and end:
                doc = await service.save_segment_video_inputs(
                    segment_id=segment_id,
                    prompt_text="角色保持原位。",
                    bindings={"additional_images": references[:8]},
                    params={},
                    expected_revision=doc.revision,
                )
                before = store.path.read_bytes()
                with pytest.raises(ValueError, match="合计 10 张，不能超过 9 张"):
                    await service._media.generate_segment_video(
                        segment_id=segment_id, expected_revision=doc.revision
                    )
                assert store.path.read_bytes() == before
                assert provider.requests == []
            doc = await service.save_segment_video_inputs(
                segment_id=segment_id,
                prompt_text="角色保持原位。",
                bindings={"additional_images": references[: 9 - int(start) - int(end)]},
                params={},
                expected_revision=doc.revision,
            )
        doc = await service._media.generate_segment_video(
            segment_id=segment_id, expected_revision=doc.revision
        )
        assert len(provider.requests) == 1
        request = provider.requests[0]
        assert (
            sum(
                len(request.slot(key)) for key in ("first_frame", "last_frame", "additional_images")
            )
            == 9
        )
        assert len(doc.generations[-1].input_asset_ids) == 9

    asyncio.run(run())
