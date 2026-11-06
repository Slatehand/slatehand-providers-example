import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from structured_director_fixtures import wav_bytes

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
