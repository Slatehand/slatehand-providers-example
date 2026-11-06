"""Qwen Image 插件：请求翻译、提示词约定、Core 分配 seed 与 Skill 交付。不加载模型。"""

from __future__ import annotations

import base64
import json

import pytest
from core.model_providers.boundary import (
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpResponse
from core.model_providers.manifest import Role
from core.model_providers.recipe import MediaInput
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorService
from core.structured_director.models import ReferenceGenerationKind

from default_model_providers_implement.comfy_core.qwen_image import (
    QwenImageGraphInputs,
    _QwenProgressServer,
    build_qwen_image_workflow,
)
from default_model_providers_implement.comfy_core.qwen_image import (
    validate_workflow as validate_qwen_workflow,
)
from default_model_providers_implement.qwen_image_request import (
    parse_request as parse_qwen_image_request,
)
from default_model_providers_implement.request_builders import prepare_qwen_image
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord
from slatehand_providers.plugins.qwen_image import MANIFEST, QwenImageProvider
from slatehand_providers.plugins.qwen_image.plugin import prompt_skills
from slatehand_providers.plugins.qwen_image.provider import canvas, to_request

PNG = b"\x89PNG\r\n\x1a\nqwen"


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        del timeout
        self.calls.append((method, url, json_body))
        if method == "POST" and url.endswith("/renders"):
            return HttpResponse(202, {}, json.dumps({"render_id": "ab" * 16}).encode())
        if url.endswith("/cancel"):
            return HttpResponse(202, {}, b"{}")
        if "/image/" in url:
            return HttpResponse(200, {}, PNG)
        body = {
            "status": "succeeded",
            "progress": 1,
            "message": "图片已生成。",
            "image": {"id": "cd" * 16, "media_type": "image/png", "bytes": 12, "sha256": "e" * 64},
        }
        return HttpResponse(200, {}, json.dumps(body).encode())


def _request(recipe_id: str, *, aspect_ratio="9:16", settings=None, **params):
    provider = QwenImageProvider("http://windows:8791", _Transport())
    plugin = PluginInstance(MANIFEST, recipes={recipe.id: provider for recipe in MANIFEST.recipes})
    registry = ProviderRegistry()
    registry.install(plugin)
    if settings is not None:
        registry.update_plugin_settings("qwen_image", {**MANIFEST.default_settings(), **settings})
    capability = MANIFEST.recipe(recipe_id).capability
    prepared = registry.prepare_recipe(capability)
    images = (MediaInput("image/png", PNG + b"1"), MediaInput("image/png", PNG + b"2"))
    media = (
        {Role.EDIT_SOURCE: images[:1], Role.REFERENCE_IMAGE: images[1:]}
        if recipe_id.endswith(".edit")
        else {Role.REFERENCE_IMAGE: images}
    )
    request, _submitted = prepared.request(
        roles={Role.PROMPT: "画面", Role.ASPECT_RATIO: aspect_ratio, Role.SEED: 7},
        media=media,
        mechanism=params,
    )
    return request


@pytest.mark.parametrize(
    ("ratio", "long_edge", "expected"),
    [
        ("16:9", 2048, (2048, 1152)),
        ("9:16", 2048, (1152, 2048)),
        ("2:1", 2048, (2048, 1024)),
        ("1:1", 1536, (1536, 1536)),
        ("2:3", 2048, (1376, 2048)),
        ("21:9", 1024, (1024, 448)),
        ("1:3", 1024, (352, 1024)),
    ],
)
def test_canvas_uses_long_edge_tier_and_32_grid(ratio, long_edge, expected) -> None:
    assert canvas(None, None, ratio, long_edge) == expected


def test_explicit_size_wins_and_must_be_complete() -> None:
    assert canvas(1024, 768, "9:16", 2048) == (1024, 768)
    with pytest.raises(ValueError, match="同时填写"):
        canvas(1024, None, "16:9", 2048)


def test_edit_request_puts_source_first_and_uses_global_quality_settings() -> None:
    dto = to_request(_request("qwen_image.edit"))
    assert (dto.width, dto.height) == (1152, 2048)
    assert (dto.steps, dto.cfg, dto.seed, dto.negative_prompt) == (25, 3.0, 7, "")
    assert [item.content for item in dto.images] == [PNG + b"1", PNG + b"2"]
    tuned = to_request(
        _request(
            "qwen_image.generate",
            aspect_ratio="3:4",
            settings={"resolution": "1k", "cfg": 1.0, "steps": 30, "negative_prompt": "模糊"},
        )
    )
    assert (tuned.width, tuned.height, tuned.steps, tuned.cfg, tuned.negative_prompt) == (
        768,
        1024,
        30,
        1.0,
        "模糊",
    )


def test_invalid_size_or_steps_are_rejected_before_submission() -> None:
    with pytest.raises(ValueError, match="32 的倍数"):
        to_request(_request("qwen_image.generate", width=1000, height=768))
    with pytest.raises(ValueError, match="整数"):
        to_request(_request("qwen_image.generate", settings={"steps": 25.5}))


def test_provider_wire_observe_cancel_and_artifact() -> None:
    transport = _Transport()
    provider = QwenImageProvider("http://windows:8791/", transport)
    handle = provider.submit_recipe(
        _request("qwen_image.generate", settings={"cfg": 1.0, "steps": 30})
    )
    assert handle == ProviderHandle("qwen-image.noctq-v4", 1, "ab" * 16)
    method, url, body = transport.calls[0]
    assert (method, url) == ("POST", "http://windows:8791/qwen-image/renders")
    assert body["width"] == 1152 and body["height"] == 2048
    assert (body["steps"], body["cfg"], body["seed"]) == (30, 1.0, 7)
    assert [base64.b64decode(item["content_base64"]) for item in body["images"]] == [
        PNG + b"1",
        PNG + b"2",
    ]
    observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED
    assert observation.artifact is not None and observation.artifact.media_type == "image/png"
    assert provider.read_artifact(handle, "cd" * 16) == PNG
    provider.cancel(handle)
    assert transport.calls[-2][1].endswith(f"/qwen-image/renders/{'ab' * 16}/cancel")
    with pytest.raises(ModelProviderError):
        provider.observe(ProviderHandle("codex.image.edit", 1, "x"))


class _RecordingQwen:
    plugin_id = "qwen-image.noctq-v4"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests = []
        self.reject = False

    def submit_recipe(self, request):
        self.requests.append(request)
        if self.reject:
            raise ModelProviderError("external_error", "服务拒绝。")
        return ProviderHandle(self.plugin_id, self.plugin_version, f"r{len(self.requests)}")

    def observe(self, handle):
        raise AssertionError("测试不观察。")

    cancel = observe

    def read_artifact(self, handle, artifact_id):
        raise AssertionError("测试不读取产物。")


def _qwen_service(store):
    provider = _RecordingQwen()
    registry = ProviderRegistry()
    registry.install(
        PluginInstance(
            MANIFEST,
            recipes={recipe.id: provider for recipe in MANIFEST.recipes},
            prompt_skills=prompt_skills,
        )
    )
    return StructuredDirectorService(store, registry=registry), provider, registry


def _keyframe_generations(document, keyframe_id):
    return [
        item
        for item in document.generations
        if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE and item.target_id == keyframe_id
    ]


# ---- Windows 私有服务：请求构造、内部请求、固定图与进度 ----


def _payload(**overrides):
    value = {
        "prompt": "画面",
        "negative_prompt": "",
        "width": 2048,
        "height": 1152,
        "steps": 25,
        "cfg": 3.0,
        "seed": 9,
        "images": [
            {"media_type": "image/png", "content_base64": base64.b64encode(PNG).decode()},
            {"media_type": "image/png", "content_base64": base64.b64encode(PNG + b"2").decode()},
        ],
    }
    value.update(overrides)
    return value


def test_prepare_writes_closed_request_that_runtime_parses(tmp_path) -> None:
    record = TaskRecord("ab" * 16, "qwen_image", "queued", 0.0, "", str(tmp_path))
    prepare_qwen_image(_payload())(record)
    written = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert written["schema"] == "slatehand_qwen_image_request_v1"
    assert written["images"] == ["image-1.png", "image-2.png"]
    request = parse_qwen_image_request(tmp_path / "request.json")
    assert [path.name for path in request.images] == ["image-1.png", "image-2.png"]
    assert (request.width, request.height, request.cfg) == (2048, 1152, 3.0)
    assert request.output_path == tmp_path / "output.png"


@pytest.mark.parametrize(
    "overrides",
    [
        {"width": 1000},
        {"steps": 61},
        {"cfg": 0.5},
        {"prompt": "   "},
        {"model": "other.safetensors"},
        {"images": [{"media_type": "image/png", "content_base64": "AAAA"}]},
    ],
)
def test_prepare_rejects_out_of_contract_requests(overrides) -> None:
    with pytest.raises(RequestError):
        prepare_qwen_image(_payload(**overrides))


def test_internal_request_only_references_task_files(tmp_path) -> None:
    record = TaskRecord("ab" * 16, "qwen_image", "queued", 0.0, "", str(tmp_path))
    prepare_qwen_image(_payload())(record)
    path = tmp_path / "request.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["images"] = ["../escape.png"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="任务目录"):
        parse_qwen_image_request(path)


def test_fixed_graph_maps_images_in_order_and_uses_custom_canvas() -> None:
    workflow = build_qwen_image_workflow(
        QwenImageGraphInputs(
            prompt="画面",
            negative_prompt="",
            width=1152,
            height=2048,
            steps=25,
            cfg=3.0,
            seed=9,
            filename_prefix="slatehand/x",
            images=("slatehand/x/image-1.png", "slatehand/x/image-2.png"),
        )
    )
    encode = workflow["5"]["inputs"]
    assert workflow[encode["images.image_1"][0]]["inputs"]["image"].endswith("image-1.png")
    assert workflow[encode["images.image_2"][0]]["inputs"]["image"].endswith("image-2.png")
    assert workflow["6"]["inputs"] == {"width": 1152, "height": 2048, "batch_size": 1}
    sampler = workflow["7"]["inputs"]
    assert (sampler["sampler_name"], sampler["scheduler"], sampler["cfg"]) == (
        "euler",
        "simple",
        3.0,
    )
    assert workflow["1"]["inputs"]["unet_name"] == "qwen\\NoctQ_V4_int8_convrot.safetensors"
    workflow["99"] = {"class_type": "LoraLoader", "inputs": {}}
    with pytest.raises(ValueError, match="类型不受允许"):
        validate_qwen_workflow(workflow)


def test_progress_is_monotonic_and_ignores_other_requests() -> None:
    reports = []
    server = _QwenProgressServer(lambda value, message: reports.append((value, message)))
    server.reset("a" * 32)
    server.send_sync("executing", {"node": "5", "prompt_id": "a" * 32})
    server.send_sync("progress", {"node": "7", "value": 5, "max": 25, "prompt_id": "a" * 32})
    server.send_sync("progress", {"node": "7", "value": 9, "max": 25, "prompt_id": "b" * 32})
    server.send_sync("executing", {"node": "8", "prompt_id": "a" * 32})
    values = [value for value, _message in reports]
    assert values == sorted(values) and values[-1] == 0.94
