from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import quote

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success
from core.model_providers.recipe import RecipeRequest

from .manifest import MANIFEST

_PHASES = {
    "queued": GenerationPhase.QUEUED,
    "generating": GenerationPhase.RUNNING,
    "done": GenerationPhase.SUCCEEDED,
    "failed": GenerationPhase.FAILED,
    "cancelled": GenerationPhase.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class HunyuanFoleyRequest:
    video: bytes
    prompt: str
    seed: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.video, bytes)
            or not 12 <= len(self.video) <= 512 * 1024 * 1024
            or self.video[4:8] != b"ftyp"
        ):
            raise ValueError("视频音效输入必须是 512 MiB 以内的 MP4。")
        if not isinstance(self.prompt, str) or not self.prompt.strip() or len(self.prompt) > 1000:
            raise ValueError("音效描述必须为 1 到 1000 字。")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("视频音效 seed 不合法。")


class HunyuanFoleyProvider:
    plugin_id = MANIFEST.plugin_id
    plugin_version = MANIFEST.plugin_version

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._url = f"{endpoint.rstrip('/')}/hunyuan-foley/generations"
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        dto = HunyuanFoleyRequest(
            request.slot("video")[0].content, request.param("prompt"), request.param("seed")
        )
        response = require_success(
            self._http.request(
                "POST",
                self._url,
                json_body={
                    "video": {"mime": "video/mp4", "base64": base64.b64encode(dto.video).decode()},
                    "prompt": dto.prompt,
                    "seed": dto.seed,
                },
            ),
            {202},
        )
        require_keys(response, required={"generation_id"})
        task_id = response["generation_id"]
        if not isinstance(task_id, str) or not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ModelProviderError("invalid_response", "视频音效任务 ID 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        data = require_success(self._http.request("GET", self._task_url(handle)), {200})
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"audio", "error_code", "retryable"},
        )
        try:
            phase = _PHASES[data["stage"]]
            progress = data["progress"]
            message = data["message"]
            retryable = data.get("retryable", False)
            error_code = data.get("error_code")
            if (
                type(progress) not in (float, int)
                or not isinstance(message, str)
                or type(retryable) is not bool
                or (error_code is not None and not isinstance(error_code, str))
            ):
                raise ValueError("状态字段类型不合法。")
            artifact = _audio(data["audio"]) if phase is GenerationPhase.SUCCEEDED else None
            return GenerationObservation(
                phase,
                progress,
                message,
                artifact,
                (error_code or "foley_generation_failed")
                if phase is GenerationPhase.FAILED
                else None,
                retryable,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelProviderError("invalid_response", "视频音效任务状态不合法。") from exc

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        require_success(self._http.request("PUT", f"{self._task_url(handle)}/abort"), {202, 409})
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        response = self._http.request(
            "GET", f"{self._task_url(handle)}/audio/{quote(artifact_id, safe='')}"
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "视频音效产物不可用。")
        return response.body

    def _task_url(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 HunyuanVideo-Foley。")
        if not re.fullmatch(r"[0-9a-f]{32}", handle.external_id):
            raise ModelProviderError("invalid_handle", "视频音效任务 ID 不合法。")
        return f"{self._url}/{handle.external_id}"


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ValueError("缺少音效产物。")
    require_keys(value, required={"id", "mime", "bytes", "sha256", "duration_seconds"})
    if (
        not isinstance(value["id"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", value["id"])
        or value["mime"] != "audio/wav"
        or type(value["bytes"]) is not int
        or value["bytes"] <= 0
        or not isinstance(value["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
        or type(value["duration_seconds"]) not in (float, int)
        or not 1 <= value["duration_seconds"] <= 15
    ):
        raise ValueError("音效产物字段不合法。")
    return ArtifactDescriptor(
        value["id"], value["mime"], value["bytes"], value["sha256"], value["duration_seconds"]
    )
