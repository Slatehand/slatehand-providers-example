from __future__ import annotations

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

from .manifest import LYRICS_MAX_LENGTH, STYLE_MAX_LENGTH

_PHASES = {
    "queued": GenerationPhase.QUEUED,
    "generating": GenerationPhase.RUNNING,
    "done": GenerationPhase.SUCCEEDED,
    "failed": GenerationPhase.FAILED,
    "cancelled": GenerationPhase.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class YuE2Request:
    style: str
    lyrics: str
    seed: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.style, str)
            or not self.style.strip()
            or len(self.style) > STYLE_MAX_LENGTH
        ):
            raise ValueError(f"风格描述必须是 1 到 {STYLE_MAX_LENGTH} 个字符。")
        if not isinstance(self.lyrics, str) or len(self.lyrics) > LYRICS_MAX_LENGTH:
            raise ValueError(f"歌词不能超过 {LYRICS_MAX_LENGTH} 个字符。")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed < 2**63
        ):
            raise ValueError("歌曲生成 seed 不合法。")


def to_request(contract: RecipeRequest) -> YuE2Request:
    return YuE2Request(
        str(contract.param("prompt")),
        str(contract.param("lyrics")),
        int(contract.param("seed")),
    )


class YuE2Provider:
    plugin_id = "yue2"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def submit(self, request: YuE2Request) -> ProviderHandle:
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/yue2/generations",
                json_body={"style": request.style, "lyrics": request.lyrics, "seed": request.seed},
            ),
            {202},
        )
        require_keys(data, required={"generation_id"})
        task_id = data["generation_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ModelProviderError("invalid_response", "YuE2 generation_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle) -> GenerationObservation:
        task_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/yue2/generations/{quote(task_id)}"),
            {200},
        )
        require_keys(
            data,
            required={"stage", "progress", "message"},
            optional={"audio", "error_code", "retryable"},
        )
        phase = _PHASES.get(data["stage"])
        if phase is None:
            raise ModelProviderError("invalid_response", "YuE2 stage 不合法。")
        artifact = _audio(data.get("audio")) if phase is GenerationPhase.SUCCEEDED else None
        return GenerationObservation(
            phase,
            float(data["progress"]),
            str(data["message"]),
            artifact,
            str(data.get("error_code") or "song_generation_failed")
            if phase is GenerationPhase.FAILED
            else None,
            bool(data.get("retryable", False)),
        )

    def cancel(self, handle) -> GenerationObservation:
        task_id = self._id(handle)
        require_success(
            self._http.request("PUT", f"{self._endpoint}/yue2/generations/{quote(task_id)}/abort"),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle, artifact_id: str) -> bytes:
        task_id = self._id(handle)
        response = self._http.request(
            "GET",
            f"{self._endpoint}/yue2/generations/{quote(task_id)}/audio/"
            f"{quote(artifact_id, safe='')}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "歌曲产物不可用。")
        return response.body

    def _id(self, handle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 YuE2 插件。")
        return handle.external_id


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "YuE2 完成响应缺少 audio。")
    require_keys(value, required={"id", "mime", "bytes", "sha256"}, optional={"duration_seconds"})
    return ArtifactDescriptor(
        str(value["id"]),
        str(value["mime"]),
        int(value["bytes"]),
        str(value["sha256"]),
        None if value.get("duration_seconds") is None else float(value["duration_seconds"]),
    )
