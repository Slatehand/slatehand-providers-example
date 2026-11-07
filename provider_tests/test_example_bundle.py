"""example bundle：清单、部署配置读取、默认部署插件顺序与随 Core 启停的服务。"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.model_providers.bundle import BundleContext
from server.provider_bundles import load_factory, read_provider_manifest

from slatehand_providers.bundle import create_bundle
from slatehand_providers.deployment import ENV_FILE, TOKEN_FILE, read_deployment
from slatehand_providers.services import MacProviderService, WhisperService

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
WINDOWS = {
    "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT": "http://10.0.0.5:8791",
    "SLATEHAND_WINDOWS_SSH_TARGET": "gpu-node",
    "SLATEHAND_WINDOWS_REPOSITORY_ROOT": "'E:\\Project\\slatehand-providers-example'",
    "SLATEHAND_WINDOWS_LISTEN_ADDRESS": "10.0.0.5",
}


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch) -> None:
    for key in list(__import__("os").environ):
        if key.startswith("SLATEHAND_"):
            monkeypatch.delenv(key)
    # 测试机可能装有 whisper-server；默认不让它参与。
    monkeypatch.setattr("slatehand_providers.deployment.shutil.which", lambda name: None)


def _provider(tmp_path: Path, settings: dict[str, str], *, token: bool = True) -> Path:
    lines = ["# 本机部署", *(f"{key}={value}" for key, value in settings.items())]
    (tmp_path / ENV_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if token:
        (tmp_path / TOKEN_FILE).parent.mkdir(parents=True)
        (tmp_path / TOKEN_FILE).write_text("t" * 40, encoding="ascii")
    return tmp_path


def _context(directory: Path) -> BundleContext:
    return BundleContext(directory, directory / "runtime")


def test_manifest_loads_the_example_factory() -> None:
    manifest = read_provider_manifest(PROVIDER_ROOT)
    assert manifest.name == "example" and manifest.requires == ()
    assert load_factory(manifest) is create_bundle


def test_full_deployment_installs_plugins_in_priority_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("slatehand_providers.bundle.sys.platform", "darwin")
    bundle = create_bundle(_context(_provider(tmp_path, WINDOWS)))

    assert [plugin.plugin_id for plugin in bundle.plugins] == [
        "codex_image",
        "agy_image",
        "demucs_audio",
        "breeze_tts2",
        "minimax_h3",
        "seedvr2_7b_sharp_fp8",
        "stable_audio_3",
        "yue2",
        "qwen_image",
        "indextts2",
    ]
    # Windows 节点的启停与心跳由工作区脚本手动管理，Core 只装插件。
    assert [type(service) for service in bundle.services] == [MacProviderService]


def test_without_token_only_mac_services_are_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("slatehand_providers.bundle.sys.platform", "linux")
    bundle = create_bundle(_context(_provider(tmp_path, {}, token=False)))
    assert [plugin.plugin_id for plugin in bundle.plugins] == [
        "codex_image",
        "agy_image",
        "demucs_audio",
    ]
    assert bundle.services == ()


def test_windows_node_needs_only_endpoint_and_token(tmp_path: Path) -> None:
    settings = {
        "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT": "http://10.0.0.5:8791",
        "SLATEHAND_AUTOSTART_MAC_PROVIDER": "0",
    }
    bundle = create_bundle(_context(_provider(tmp_path, settings)))
    assert "minimax_h3" in [plugin.plugin_id for plugin in bundle.plugins]
    assert bundle.services == ()


def test_local_whisper_is_started_when_binary_and_model_exist(tmp_path: Path) -> None:
    server = tmp_path / "whisper-server"
    server.write_text("#!/bin/sh\n")
    server.chmod(0o755)
    model = tmp_path / "model.bin"
    model.write_bytes(b"x")
    settings = {
        "SLATEHAND_WHISPER_SERVER": str(server),
        "SLATEHAND_WHISPER_MODEL": str(model),
        "SLATEHAND_AUTOSTART_MAC_PROVIDER": "0",
    }
    bundle = create_bundle(_context(_provider(tmp_path, settings, token=False)))
    assert "whisper_asr" in [plugin.plugin_id for plugin in bundle.plugins]
    assert [type(service) for service in bundle.services] == [WhisperService]


def test_environment_overrides_the_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SLATEHAND_MAC_PROVIDER_PORT", "9000")
    settings = {
        "SLATEHAND_MAC_PROVIDER_PORT": "8792",
        "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT": "http://10.0.0.5:8791",
    }
    deployment = read_deployment(_provider(tmp_path, settings))
    assert deployment.mac_endpoint == "http://127.0.0.1:9000"
    assert deployment.windows is not None
    assert deployment.windows.breeze_endpoint == "http://10.0.0.5:8791"


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"SLATEHAND_TYPO": "1"}, "已知的 SLATEHAND_"),
        ({"SLATEHAND_MAC_PROVIDER_PORT": "abc"}, "端口号"),
        ({"SLATEHAND_AUTOSTART_MAC_PROVIDER": "yes"}, "0 或 1"),
        ({"SLATEHAND_WINDOWS_RUNTIME_ENDPOINT": "http://u:p@host"}, "HTTP 地址"),
        ({}, "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT"),
        ({"SLATEHAND_AUTOSTART_WINDOWS_PROVIDER": "0"}, "已知的 SLATEHAND_"),
    ],
)
def test_invalid_deployment_settings_are_rejected(tmp_path: Path, settings, message) -> None:
    with pytest.raises(ValueError, match=message):
        read_deployment(_provider(tmp_path, settings))
