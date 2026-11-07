"""H3 运行节点：按实例设置选择新提交的节点，句柄回到提交时的节点；Colab 部署配置与隧道。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from core.model_providers.boundary import ModelProviderError, ProviderHandle
from core.model_providers.bundle import BundleContext
from core.model_providers.http import HttpResponse
from core.model_providers.recipe import MediaInput, build_recipe_request

from slatehand_providers.bundle import create_bundle
from slatehand_providers.colab_tunnel import ColabTunnelService
from slatehand_providers.deployment import COLAB_TOKEN_FILE, ENV_FILE, TOKEN_FILE, read_deployment
from slatehand_providers.plugins.minimax_h3 import MANIFEST
from slatehand_providers.plugins.minimax_h3.plugin import plugin_instance

PNG = b"\x89PNG\r\n\x1a\nbytes"


class Transport:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        self.calls.append((method, url))
        if method == "POST":
            body = {"job_token": f"{self.name}-job", "queue_position": 0}
            return HttpResponse(202, {}, json.dumps(body).encode())
        body = {"stage": "queued", "ratio": 0.0, "description": self.name}
        return HttpResponse(200, {}, json.dumps(body).encode())


def _request(node: str):
    return build_recipe_request(
        MANIFEST,
        "minimax_h3.fl2va",
        inputs={"first_frame": (MediaInput("image/png", PNG),), "last_frame": ()},
        params={"prompt": "走进房间", "duration_seconds": 3, "seed": 1, "aspect_ratio": "16:9"},
        settings={**MANIFEST.default_settings(), "node": node},
    )


def test_node_setting_routes_new_submissions_and_handles_return_to_their_node() -> None:
    windows, colab = Transport("windows"), Transport("colab")
    plugin = plugin_instance("http://win", windows, nodes={"colab": ("http://colab", colab)})
    router = plugin.recipes["minimax_h3.fl2va"]

    old = router.submit_recipe(_request("windows"))
    new = router.submit_recipe(_request("colab"))

    # 默认节点句柄保持原始 token，与切换前持久化的句柄兼容。
    assert old.external_id == "windows-job"
    assert new.external_id == "colab:colab-job"
    assert (old.plugin_id, old.plugin_version) == (new.plugin_id, new.plugin_version)
    assert router.observe(old).message == "windows"
    assert router.observe(new).message == "colab"
    assert windows.calls[-1] == ("GET", "http://win/minimax-h3/fl2va/clips/windows-job")
    assert colab.calls[-1] == ("GET", "http://colab/minimax-h3/fl2va/clips/colab-job")


def test_unconfigured_node_is_rejected_with_a_clear_error() -> None:
    plugin = plugin_instance("http://win", Transport("windows"))
    with pytest.raises(ModelProviderError) as error:
        plugin.recipes["minimax_h3.ref2va"].submit_recipe(_request("colab"))
    assert error.value.code == "node_unavailable"
    assert "Colab G4" in str(error.value)


def test_colab_only_plugin_routes_prefixed_handles() -> None:
    colab = Transport("colab")
    router = plugin_instance(nodes={"colab": ("http://colab", colab)}).recipes["minimax_h3.fl2va"]
    handle = ProviderHandle(router.plugin_id, router.plugin_version, "colab:abc")
    assert router.observe(handle).message == "colab"
    with pytest.raises(ModelProviderError):
        router.observe(ProviderHandle(router.plugin_id, router.plugin_version, "abc"))


def test_node_setting_defaults_to_local_windows_and_is_summarized() -> None:
    defaults = MANIFEST.default_settings()
    assert defaults["node"] == "windows"
    assert MANIFEST.settings_summary({**defaults, "node": "colab"}).endswith("· Colab G4")
    with pytest.raises(ValueError):
        MANIFEST.validate_settings({**defaults, "node": "aws"})


# ------------------------------------------------------------ 部署配置与 bundle


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("SLATEHAND_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr("slatehand_providers.deployment.shutil.which", lambda name: None)


def _provider(tmp_path: Path, settings: dict[str, str], *, windows: bool) -> Path:
    lines = [f"{key}={value}" for key, value in settings.items()]
    (tmp_path / ENV_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / COLAB_TOKEN_FILE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / COLAB_TOKEN_FILE).write_text("c" * 64, encoding="ascii")
    if windows:
        (tmp_path / TOKEN_FILE).write_text("t" * 40, encoding="ascii")
    return tmp_path


def test_colab_node_is_read_from_its_token_and_session(tmp_path: Path) -> None:
    deployment = read_deployment(
        _provider(tmp_path, {"SLATEHAND_COLAB_SESSION": "slate"}, windows=False)
    )
    assert deployment.windows is None
    assert deployment.colab is not None
    assert (deployment.colab.session, deployment.colab.endpoint) == (
        "slate",
        "http://127.0.0.1:18791",
    )


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({}, "SLATEHAND_COLAB_SESSION"),
        ({"SLATEHAND_COLAB_SESSION": "a b"}, "SLATEHAND_COLAB_SESSION"),
        ({"SLATEHAND_COLAB_SESSION": "slate", "SLATEHAND_COLAB_LOCAL_PORT": "80"}, "端口"),
    ],
)
def test_invalid_colab_settings_are_rejected(tmp_path: Path, settings, message) -> None:
    with pytest.raises(ValueError, match=message):
        read_deployment(_provider(tmp_path, settings, windows=False))


def test_bundle_installs_one_h3_plugin_with_both_nodes_and_the_tunnel(tmp_path: Path) -> None:
    settings = {
        "SLATEHAND_COLAB_SESSION": "slate",
        "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT": "http://10.0.0.5:8791",
        "SLATEHAND_AUTOSTART_WINDOWS_PROVIDER": "0",
        "SLATEHAND_AUTOSTART_MAC_PROVIDER": "0",
    }
    bundle = create_bundle(
        BundleContext(_provider(tmp_path, settings, windows=True), tmp_path / "runtime")
    )
    h3 = [plugin for plugin in bundle.plugins if plugin.plugin_id == "minimax_h3"]
    assert len(h3) == 1
    assert h3[0].recipes["minimax_h3.ref2va"].nodes == ("windows", "colab")
    assert any(isinstance(service, ColabTunnelService) for service in bundle.services)


def test_colab_only_bundle_still_installs_h3(tmp_path: Path) -> None:
    settings = {"SLATEHAND_COLAB_SESSION": "slate", "SLATEHAND_AUTOSTART_MAC_PROVIDER": "0"}
    bundle = create_bundle(
        BundleContext(_provider(tmp_path, settings, windows=False), tmp_path / "runtime")
    )
    (h3,) = [plugin for plugin in bundle.plugins if plugin.plugin_id == "minimax_h3"]
    assert h3.recipes["minimax_h3.fl2va"].nodes == ("colab",)
    assert [type(service) for service in bundle.services] == [ColabTunnelService]


# ------------------------------------------------------------ 隧道


def _tunnel(tmp_path: Path, sessions_stdout: str, popen=None) -> ColabTunnelService:
    deployment = read_deployment(
        _provider(tmp_path, {"SLATEHAND_COLAB_SESSION": "slate"}, windows=False)
    ).colab

    def run(command, **_kwargs):
        assert command[1:] == ["sessions"]
        return subprocess.CompletedProcess(command, 0, sessions_stdout, "")

    def refuse(*_args, **_kwargs):
        raise AssertionError("会话缺席时不得建立 SSH（colab ssh 会自动开新 VM）。")

    return ColabTunnelService(deployment, run=run, popen=popen or refuse)


def test_tunnel_only_connects_when_the_session_is_listed(tmp_path: Path) -> None:
    other = "[slate-old] gpu-x | Hardware: G4\n[?] m-s-1 | Hardware: CPU\n"
    assert not _tunnel(tmp_path, other).session_running()
    assert _tunnel(tmp_path, "[slate] gpu-g4 | Hardware: G4\n").session_running()


def test_tunnel_waits_without_spawning_ssh_while_session_is_absent(tmp_path: Path) -> None:
    tunnel = _tunnel(tmp_path, "[colab] No active sessions found on server.\n")
    waits: list[float] = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        tunnel._stop.set()
        return True

    tunnel._wait = wait
    tunnel._loop()
    assert waits == [30.0]


def test_tunnel_forwards_loopback_to_the_vm_service_port(tmp_path: Path) -> None:
    command = _tunnel(tmp_path, "").ssh_command()
    assert command[:2] == ["ssh", "-N"]
    assert "127.0.0.1:18791:127.0.0.1:8791" in command
    assert "ProxyCommand=colab ssh --proxy-mode -s slate" in command
    assert "ExitOnForwardFailure=yes" in command
