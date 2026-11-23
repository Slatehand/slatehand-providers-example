"""HunyuanVideo-Foley XXL 的 Playground、HTTP 与产物回收契约。"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import wave
from pathlib import Path

import pytest
from core.model_providers.http import UrllibTransport
from core.model_providers.registry import ProviderRegistry
from core.playground.models import RunPhase
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from tests.playground_fixtures import real_mp4_bytes

from default_model_providers_implement import server as server_module
from default_model_providers_implement.resource_manager import RunResult
from slatehand_providers.plugins.hunyuan_foley.plugin import plugin_instance

RECIPE = "hunyuan_foley.generate"


def test_foley_playground_round_trip(tmp_path: Path, monkeypatch) -> None:
    video = real_mp4_bytes(50, 2)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00" * (2 * 48000 * 2))
    wav_bytes = output.getvalue()
    invocations = []

    def fake_runner(record, cancel, progress):
        root = Path(record.task_dir)
        invocations.append(
            ((root / "input.mp4").read_bytes(), json.loads((root / "request.json").read_bytes()))
        )
        wav_path = root / "output.wav"
        wav_path.write_bytes(wav_bytes)
        return RunResult(wav_path, "audio/wav")

    monkeypatch.setattr(server_module, "hunyuan_foley_runner", fake_runner)
    model = server_module.ModelApiServer(
        ("127.0.0.1", 0), tmp_path / "runtime", enabled_services={"hunyuan_foley"}
    )
    model.manager.start()
    thread = threading.Thread(target=model.serve_forever, daemon=True)
    thread.start()
    host, port = model.server_address
    endpoint = f"http://{host}:{port}"

    async def run_playground() -> None:
        registry = ProviderRegistry()
        registry.install(plugin_instance(endpoint))
        service = PlaygroundService(PlaygroundStore(tmp_path / "playground"), registry)
        spec = service.capability_specs()[RECIPE]
        assert spec.output_media_types == {"audio/wav"}
        asset = await service.import_asset(media_type="video/mp4", content=video, filename="雨.mp4")
        assert asset.duration_seconds == 2
        run = await service.submit_run(
            RECIPE, {"video_asset_id": asset.id, "prompt": "雨滴落地", "seed": 7}, note=None
        )
        async with asyncio.timeout(5):
            while run.phase in (RunPhase.QUEUED, RunPhase.RUNNING):
                await asyncio.sleep(0.01)
                run = await service.refresh_run(run.id)
        assert run.phase is RunPhase.SUCCEEDED
        artifact_id = run.output_asset_id
        assert artifact_id is not None
        artifact, content = service.read_asset(artifact_id)
        assert (artifact.media_type, artifact.duration_seconds, content) == (
            "audio/wav",
            2,
            wav_bytes,
        )

        short = await service.import_asset(
            media_type="video/mp4", content=real_mp4_bytes(10, 0.4), filename="太短.mp4"
        )
        with pytest.raises(ValueError, match="1 到 15 秒"):
            await service.submit_run(
                RECIPE, {"video_asset_id": short.id, "prompt": "雨滴落地", "seed": 7}, note=None
            )

    try:
        asyncio.run(run_playground())
        assert invocations == [
            (video, {"schema": "hunyuan_foley_request_v1", "prompt": "雨滴落地", "seed": 7})
        ]
        response = UrllibTransport().request(
            "POST",
            f"{endpoint}/hunyuan-foley/generations",
            json_body={"video": {}, "prompt": "雨声", "seed": 7, "model_size": "xl"},
        )
        assert response.status == 422
    finally:
        model.shutdown()
        model.manager.shutdown()
        model.server_close()
        thread.join(5)
