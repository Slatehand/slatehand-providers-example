from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from core.model_providers.contracts import AudioRemixRequest

from default_model_providers_implement.request_builders import (
    prepare_demucs_audio_separation,
)
from default_model_providers_implement.server import build_parser
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord


def _record(root: Path, kind: str) -> TaskRecord:
    root.mkdir()
    return TaskRecord("a" * 32, kind, "queued", 0.0, "等待", str(root))


def _media(media_type: str, content: bytes) -> dict[str, str]:
    return {"mime": media_type, "base64": base64.b64encode(content).decode("ascii")}


def _fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


def _fake_wav() -> bytes:
    return b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 32


class VideoAudioProviderContractTests(unittest.TestCase):
    def test_server_cli_accepts_audio_services(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--state-root",
                "/tmp/slatehand-provider-test",
                "--services",
                "demucs_audio_separation",
            ]
        )
        self.assertEqual(arguments.services, "demucs_audio_separation")

    def test_request_builders_write_only_fixed_media_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            separation_record = _record(root / "separation", "demucs_audio_separation")
            prepare_demucs_audio_separation(
                {"video": _media("video/mp4", _fake_mp4()), "stem": "voice"}
            )(separation_record)
            separation = json.loads(
                (Path(separation_record.task_dir) / "request.json").read_text(encoding="utf-8")
            )
            self.assertEqual(separation["stem"], "voice")
            self.assertEqual(separation["input"], "input.mp4")
            self.assertNotIn("path", json.dumps(separation))

    def test_request_builders_reject_unknown_fields_and_invalid_stem(self) -> None:
        with self.assertRaises(RequestError):
            prepare_demucs_audio_separation(
                {
                    "video": _media("video/mp4", _fake_mp4()),
                    "stem": "music",
                    "path": "/tmp/input.mp4",
                }
            )

    def test_remix_request_rejects_non_numeric_or_non_finite_gain(self) -> None:
        for value in (True, "0", float("nan"), float("inf"), -101, 25):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AudioRemixRequest(_fake_mp4(), _fake_wav(), _fake_wav(), value, 0)

    def test_remix_request_rejects_invalid_gain_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须同时提供"):
            AudioRemixRequest(
                _fake_mp4(),
                _fake_wav(),
                _fake_wav(),
                0,
                0,
                voice_gain_start_seconds=0.2,
            )
        with self.assertRaisesRegex(ValueError, "时间范围不合法"):
            AudioRemixRequest(
                _fake_mp4(),
                _fake_wav(),
                _fake_wav(),
                0,
                0,
                background_gain_start_seconds=0.8,
                background_gain_end_seconds=0.2,
            )


if __name__ == "__main__":
    unittest.main()
