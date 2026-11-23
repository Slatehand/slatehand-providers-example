import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from core.model_providers.http import UrllibTransport
from structured_director_fixtures import wav_bytes

from default_model_providers_implement import whisper_runner
from default_model_providers_implement.server import ModelApiServer
from slatehand_providers.plugins.whisper_asr import (
    WhisperASRProvider,
    WhisperASRRequest,
)


class _WhisperStub(BaseHTTPRequestHandler):
    requests: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.requests.append(self.rfile.read(length))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"text": " 你好，Slatehand. "}).encode())

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture()
def whisper_stub():
    _WhisperStub.requests = []
    server = HTTPServer(("127.0.0.1", 0), _WhisperStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_whisper_provider_posts_wav_and_returns_trimmed_text(whisper_stub: str) -> None:
    provider = WhisperASRProvider(whisper_stub)
    result = provider.transcribe(WhisperASRRequest(wav_bytes(), "audio/wav"))
    assert result.text == "你好，Slatehand."
    request = _WhisperStub.requests[0]
    assert b'name="file"; filename="reference.wav"' in request
    assert b'name="language"' in request and b"auto" in request
    assert b'name="translate"' in request and b"false" in request


def test_colab_whisper_uses_authenticated_model_service(tmp_path: Path, monkeypatch) -> None:
    audio = wav_bytes()
    binary = tmp_path / "whisper-cli"
    model = tmp_path / "model.bin"
    binary.touch(mode=0o755)
    model.touch()
    monkeypatch.setenv("SLATEHAND_WHISPER_CLI", str(binary))
    monkeypatch.setenv("SLATEHAND_WHISPER_MODEL", str(model))

    def run(command, **kwargs):
        if command[0] == "ffmpeg":
            assert Path(command[command.index("-i") + 1]).read_bytes() == audio
            Path(command[-1]).write_bytes(audio)
        else:
            assert command[0] == str(binary)
            assert command[command.index("-l") + 1] == "zh"
            Path(command[-1]).with_suffix(".txt").write_text(" 你好，Colab。 ", encoding="utf-8")
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(whisper_runner.subprocess, "run", run)
    token = "test-token-with-at-least-thirty-two-characters"
    with ModelApiServer(
        ("127.0.0.1", 0), tmp_path, enabled_services={"mock"}, auth_token=token, whisper_asr=True
    ) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        try:
            denied = UrllibTransport().request(
                "POST", f"{endpoint}/whisper/transcriptions", json_body={}
            )
            assert denied.status == 401
            provider = WhisperASRProvider(
                endpoint, UrllibTransport({"Authorization": f"Bearer {token}"})
            )
            result = provider.transcribe(WhisperASRRequest(audio, "audio/wav", "zh"))
            assert result.text == "你好，Colab。"
        finally:
            server.shutdown()
            thread.join(timeout=2)
