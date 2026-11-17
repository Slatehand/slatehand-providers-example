"""真实 HTTP：上传前断线、受理回执丢失、重启、并发去重与迟到上传取消。"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from core.model_providers.boundary import GenerationPhase, ModelProviderError
from core.model_providers.http import UrllibTransport
from core.model_providers.recipe import MediaInput, build_recipe_request
from media_samples import png_bytes

from default_model_providers_implement import server as api
from default_model_providers_implement.task_store import TaskStore
from slatehand_providers.plugins.minimax_h3 import MANIFEST
from slatehand_providers.plugins.minimax_h3.plugin import plugin_instance


class FaultyTransport:
    def __init__(self):
        self.http = UrllibTransport()
        self.calls = []
        self.offline = False
        self.drop_reply = False
        self.drop_upload = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.offline or (method == "POST" and self.drop_upload):
            raise ModelProviderError("transport_error", "测试断线", retryable=True)
        result = self.http.request(method, url, **kwargs)
        if method == "POST" and self.drop_reply:
            self.drop_reply = False
            assert result.status == 202
            raise ModelProviderError("transport_error", "测试受理后丢失回执", retryable=True)
        return result


@pytest.fixture
def node(tmp_path):
    servers = []

    def start():
        server = api.ModelApiServer(
            ("127.0.0.1", 0), tmp_path / "remote", enabled_services={"h3_fl2va", "h3_ref2va"}
        )
        # 不启动 GPU worker，使测试能精确断言进入队列的次数。
        server.manager.activate()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return server, f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(5)


def router(endpoint, directory, mode="ref2va", transport=None):
    return plugin_instance(
        nodes={"colab": (endpoint, transport)}, runtime_directory=directory
    ).recipes["minimax_h3." + mode]


def request(mode="ref2va"):
    inputs = {"first_frame": (MediaInput("image/png", png_bytes("submission")),)}
    return build_recipe_request(
        MANIFEST,
        "minimax_h3." + mode,
        inputs=inputs,
        params={
            "prompt": "固定镜头，小球静止。",
            "duration_seconds": 0.2,
            "seed": 7,
            "aspect_ratio": "16:9",
        },
        settings={**MANIFEST.default_settings(), "node": "colab", "preset": "turbo_v2"},
    )


def spool(directory, handle, mode="ref2va"):
    return directory / "colab" / mode / (handle.external_id.removeprefix("colab:") + ".json")


@pytest.mark.parametrize("mode", ["ref2va", "fl2va"])
def test_handle_is_durable_before_network_and_offline_upload_recovers(node, tmp_path, mode):
    server, endpoint = node()
    transport = FaultyTransport()
    provider = router(endpoint, tmp_path / "outbox", mode, transport)
    handle = provider.submit_recipe(request(mode))
    assert transport.calls == []
    assert server.store.list_recoverable() == []
    assert spool(tmp_path / "outbox", handle, mode).stat().st_mode & 0o777 == 0o600
    transport.drop_upload = True
    with pytest.raises(ModelProviderError, match="测试断线"):
        provider.observe(handle)
    assert server.store.list_recoverable() == []
    transport.drop_upload = False
    assert provider.observe(handle).phase is GenerationPhase.QUEUED
    assert len(server.store.list_recoverable()) == 1
    uploads = [c for c in transport.calls if c[0] == "POST"]
    assert len({c[2]["json_body"]["submission_id"] for c in uploads}) == 1
    assert uploads[0][2]["timeout"] == 120


@pytest.mark.parametrize("mode", ["ref2va", "fl2va"])
def test_lost_acceptance_reply_recovers_after_plugin_restart_without_resubmitting(
    node, tmp_path, mode
):
    server, endpoint = node()
    transport = FaultyTransport()
    transport.drop_reply = True
    provider = router(endpoint, tmp_path / "outbox", mode, transport)
    handle = provider.submit_recipe(request(mode))
    with pytest.raises(ModelProviderError, match="丢失回执"):
        provider.observe(handle)
    assert len(server.store.list_recoverable()) == 1
    restored_transport = FaultyTransport()
    restored = router(endpoint, tmp_path / "outbox", mode, restored_transport)
    assert restored.observe(handle).phase is GenerationPhase.QUEUED
    assert [c[0] for c in restored_transport.calls] == ["GET"]
    assert json.loads(spool(tmp_path / "outbox", handle, mode).read_text())["payload"] is None
    remote = TaskStore(tmp_path / "remote").get(handle.external_id.removeprefix("colab:"))
    assert remote.submission_digest is not None
    assert len(server.manager.managers[0]._pending) == 1


def test_identical_parallel_posts_and_server_restart_keep_one_task(node, tmp_path):
    server, endpoint = node()
    transport = FaultyTransport()
    provider = router(endpoint, tmp_path / "outbox", transport=transport)
    handle = provider.submit_recipe(request())
    provider.observe(handle)
    upload = next(c for c in transport.calls if c[0] == "POST")
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: UrllibTransport().request(*upload[:2], **upload[2]), range(12))
        )
    assert all(r.status == 202 for r in responses)
    assert len(server.store.list_recoverable()) == 1
    assert len(server.manager.managers[0]._pending) == 1
    server.shutdown()
    server.server_close()
    restored, new_endpoint = node()
    response = UrllibTransport().request(
        "POST", new_endpoint + "/minimax-h3/ref2va/renders", **upload[2]
    )
    assert response.status == 202
    assert len(restored.store.list_recoverable()) == 1
    conflict = UrllibTransport().request(
        "POST",
        new_endpoint + "/minimax-h3/ref2va/renders",
        json_body={**upload[2]["json_body"], "random_seed": 8},
    )
    assert conflict.status == 409
    assert len(restored.store.list_recoverable()) == 1


def test_cancel_before_upload_is_local_and_does_not_execute(node, tmp_path):
    server, endpoint = node()
    transport = FaultyTransport()
    provider = router(endpoint, tmp_path / "outbox", transport=transport)
    handle = provider.submit_recipe(request())
    assert provider.cancel(handle).phase is GenerationPhase.CANCELLED
    assert transport.calls == []
    assert server.store.list_recoverable() == []


def test_cancel_after_uncertain_upload_blocks_late_request_even_after_restart(node, tmp_path):
    server, endpoint = node()
    transport = FaultyTransport()
    transport.drop_upload = True
    provider = router(endpoint, tmp_path / "outbox", transport=transport)
    handle = provider.submit_recipe(request())
    with pytest.raises(ModelProviderError):
        provider.observe(handle)
    upload = next(c for c in transport.calls if c[0] == "POST")
    assert provider.cancel(handle).phase is GenerationPhase.CANCELLED
    late = UrllibTransport().request(*upload[:2], **upload[2])
    assert late.status == 202
    task_id = handle.external_id.removeprefix("colab:")
    assert server.store.get(task_id).state == "cancelled"
    assert server.manager.managers[0]._pending == []
    restored = TaskStore(tmp_path / "remote")
    assert restored.get(task_id).state == "cancelled"


def test_accepted_task_is_never_recreated_if_remote_state_disappears(node, tmp_path):
    server, endpoint = node()
    transport = FaultyTransport()
    provider = router(endpoint, tmp_path / "outbox", transport=transport)
    handle = provider.submit_recipe(request())
    provider.observe(handle)
    server.store._records.clear()
    result = provider.observe(handle)
    assert result.phase is GenerationPhase.FAILED
    assert result.error_code == "remote_task_missing"
    assert len([c for c in transport.calls if c[0] == "POST"]) == 1


def test_explicit_new_submission_creates_new_id_even_with_identical_payload(node, tmp_path):
    server, endpoint = node()
    provider = router(endpoint, tmp_path / "outbox")
    first, second = provider.submit_recipe(request()), provider.submit_recipe(request())
    assert first != second
    provider.observe(first)
    provider.observe(second)
    assert len(server.store.list_recoverable()) == 2


def test_restart_during_request_preparation_does_not_execute_partial_input(tmp_path):
    store = TaskStore(tmp_path / "remote")
    record = store.create(
        "h3_ref2va", task_id="a" * 32, submission_digest="b" * 64, state="preparing"
    )
    restored = TaskStore(tmp_path / "remote").get(record.task_id)
    assert restored.state == "failed"
    assert restored.error_code == "request_preparation_interrupted"


def test_core_keeps_one_run_and_handle_through_offline_and_lost_reply(node, tmp_path, monkeypatch):
    import asyncio
    import time

    from core.model_providers.registry import ProviderRegistry
    from core.playground.models import RunPhase
    from core.playground.service import PlaygroundService
    from core.playground.store import PlaygroundStore
    from media_samples import mp4_bytes

    from default_model_providers_implement.resource_manager import RunResult

    executed = []
    movie = mp4_bytes("idempotent", 0.2)

    def runner(record, _cancel, _progress):
        executed.append(record.task_id)
        output = Path(record.task_dir) / "output.mp4"
        output.write_bytes(movie)
        return RunResult(output, "video/mp4")

    monkeypatch.setattr(api, "create_h3_ref2va_comfy_core_runner", lambda _: runner)
    server, endpoint = node()
    transport = FaultyTransport()
    directory = tmp_path / "outbox"
    store = PlaygroundStore(tmp_path / "playground")

    def service():
        registry = ProviderRegistry()
        registry.install(
            plugin_instance(nodes={"colab": (endpoint, transport)}, runtime_directory=directory)
        )
        registry.update_plugin_settings(
            "minimax_h3", {**MANIFEST.default_settings(), "node": "colab", "preset": "turbo_v2"}
        )
        return PlaygroundService(store, registry)

    async def exercise():
        core = service()
        image = await core.import_asset(
            media_type="image/png", content=png_bytes("small"), filename="small.png"
        )
        run = await core.submit_run(
            "minimax_h3.ref2va",
            {
                "first_frame_asset_id": image.id,
                "last_frame_asset_id": None,
                "additional_images": [],
                "reference_audios": [],
                "reference_videos": [],
                "prompt": "小球静止。",
                "duration_seconds": 0.2,
                "seed": 8,
                "aspect_ratio": "16:9",
            },
            note=None,
        )
        assert run.phase is RunPhase.QUEUED
        handle = run.external_id
        assert handle is not None and transport.calls == []
        transport.offline = True
        unavailable = await core.refresh_run(run.id)
        assert unavailable.external_id == handle
        assert unavailable.error_code == "provider_unreachable"
        transport.offline = False
        transport.drop_reply = True
        uncertain = await core.refresh_run(run.id)
        assert uncertain.external_id == handle
        assert len(server.store.list_recoverable()) == 1
        core = service()
        server.manager.start()
        deadline = time.monotonic() + 5
        while True:
            observed = await core.refresh_run(run.id)
            if observed.phase is RunPhase.SUCCEEDED:
                break
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        assert observed.external_id == handle
        assert len(core.store.read().runs) == 1
        assert len(executed) == 1
        assert core.store.read_asset(observed.output_asset_id)[1] == movie
        assert len([c for c in transport.calls if c[0] == "POST"]) == 1

    try:
        asyncio.run(exercise())
    finally:
        server.manager.shutdown()


def test_explicit_rejection_is_terminal_and_not_automatically_retried(node, tmp_path):
    from slatehand_providers.plugins.minimax_h3.submissions import H3SubmissionTransport

    server, endpoint = node()
    transport = FaultyTransport()
    http = H3SubmissionTransport(endpoint, "ref2va", tmp_path / "outbox", transport)
    staged = http.request(
        "POST", endpoint + "/minimax-h3/ref2va/renders", json_body={"invalid": True}
    )
    task_id = staged.json_object()["render_id"]
    for _ in range(2):
        status = http.request(
            "GET", endpoint + "/minimax-h3/ref2va/renders/" + task_id
        ).json_object()
        assert status["status"] == "failed"
        assert status["error"] == "submission_rejected"
    assert len([c for c in transport.calls if c[0] == "POST"]) == 1
    assert server.store.list_recoverable() == []
