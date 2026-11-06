"""默认部署的本机配置：Provider 目录下 Git 忽略的 ``provider.local.env`` 与 ``var/secrets/``。

``provider.local.env`` 每行 ``KEY=VALUE``（可加单/双引号，``#`` 开头为注释），同名进程环境变量优先。
未知的 ``SLATEHAND_*`` 键直接拒绝，避免拼写错误静默失效。
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ENV_FILE = "provider.local.env"
TOKEN_FILE = Path("var/secrets/windows-model-service-token")
WHISPER_MODEL = Path("var/whisper-asr/ggml-large-v3-turbo-q5_0.bin")
WHISPER_PORT = 8793

KEYS = frozenset(
    {
        "SLATEHAND_MAC_PROVIDER_PORT",
        "SLATEHAND_AUTOSTART_MAC_PROVIDER",
        "SLATEHAND_WHISPER_ENDPOINT",
        "SLATEHAND_WHISPER_SERVER",
        "SLATEHAND_WHISPER_MODEL",
        "SLATEHAND_WINDOWS_RUNTIME_ENDPOINT",
        "SLATEHAND_AUTOSTART_WINDOWS_PROVIDER",
        "SLATEHAND_WINDOWS_SSH_TARGET",
        "SLATEHAND_WINDOWS_REPOSITORY_ROOT",
        "SLATEHAND_WINDOWS_LISTEN_ADDRESS",
        "SLATEHAND_BREEZE_ENDPOINT",
    }
)


@dataclass(frozen=True, slots=True)
class WindowsDeployment:
    """Windows GPU 节点；``ssh_target`` 为空表示不由 Core 启停（服务已自行运行）。"""

    endpoint: str
    token: str
    breeze_endpoint: str
    ssh_target: str | None = None
    repository_root: str | None = None
    listen_address: str | None = None


@dataclass(frozen=True, slots=True)
class Deployment:
    mac_endpoint: str
    mac_autostart: bool
    whisper_endpoint: str | None
    # 给出时由 Core 在本机拉起 whisper.cpp 服务。
    whisper_server: Path | None
    whisper_model: Path | None
    windows: WindowsDeployment | None


def read_deployment(directory: Path, environ: Mapping[str, str] = os.environ) -> Deployment:
    values = _read_env_file(directory / ENV_FILE)
    values.update({key: value for key, value in environ.items() if key in KEYS})

    port = values.get("SLATEHAND_MAC_PROVIDER_PORT", "8792")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("SLATEHAND_MAC_PROVIDER_PORT 必须是端口号。")
    mac_endpoint = f"http://127.0.0.1:{int(port)}"

    whisper_endpoint = endpoint(values.get("SLATEHAND_WHISPER_ENDPOINT"), "Whisper")
    whisper_server = whisper_model = None
    if whisper_endpoint is None:
        binary = values.get("SLATEHAND_WHISPER_SERVER") or shutil.which("whisper-server")
        model = Path(values.get("SLATEHAND_WHISPER_MODEL") or directory / WHISPER_MODEL)
        if binary and os.access(binary, os.X_OK) and model.is_file():
            whisper_server, whisper_model = Path(binary), model
            whisper_endpoint = f"http://127.0.0.1:{WHISPER_PORT}"

    return Deployment(
        mac_endpoint=mac_endpoint,
        mac_autostart=_flag(values, "SLATEHAND_AUTOSTART_MAC_PROVIDER"),
        whisper_endpoint=whisper_endpoint,
        whisper_server=whisper_server,
        whisper_model=whisper_model,
        windows=_windows(directory, values),
    )


def _windows(directory: Path, values: dict[str, str]) -> WindowsDeployment | None:
    """只在存在 Token 文件时接入 Windows 节点。"""
    token_path = directory / TOKEN_FILE
    if not token_path.is_file():
        return None
    windows = endpoint(values.get("SLATEHAND_WINDOWS_RUNTIME_ENDPOINT"), "Windows")
    if windows is None:
        raise ValueError(
            f"已有 {TOKEN_FILE}，但 {ENV_FILE} 没有设置 SLATEHAND_WINDOWS_RUNTIME_ENDPOINT。"
        )
    token = token_path.read_text(encoding="ascii").strip()
    if not 32 <= len(token) <= 512:
        raise ValueError("Windows Provider token 长度不合法。")
    breeze = endpoint(values.get("SLATEHAND_BREEZE_ENDPOINT"), "Breeze") or windows
    if not _flag(values, "SLATEHAND_AUTOSTART_WINDOWS_PROVIDER"):
        return WindowsDeployment(windows, token, breeze)
    remote = {
        key: values.get(key, "").strip()
        for key in (
            "SLATEHAND_WINDOWS_SSH_TARGET",
            "SLATEHAND_WINDOWS_REPOSITORY_ROOT",
            "SLATEHAND_WINDOWS_LISTEN_ADDRESS",
        )
    }
    missing = [key for key, value in remote.items() if not value]
    if missing:
        raise ValueError(
            f"由 Core 启停 Windows 服务需要在 {ENV_FILE} 设置 {'、'.join(missing)}；"
            "不需要时设 SLATEHAND_AUTOSTART_WINDOWS_PROVIDER=0。"
        )
    return WindowsDeployment(windows, token, breeze, *remote.values())


def endpoint(value: str | None, label: str) -> str | None:
    if not value:
        return None
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(f"{label} 地址必须是不含凭据、查询或片段的 HTTP 地址。")
    return value.rstrip("/")


def _flag(values: dict[str, str], key: str) -> bool:
    value = values.get(key, "1")
    if value not in {"0", "1"}:
        raise ValueError(f"{key} 只能是 0 或 1。")
    return value == "1"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in KEYS:
            raise ValueError(f"{path.name} 第 {number} 行不是已知的 SLATEHAND_* 设置：{key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values
