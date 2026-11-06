from __future__ import annotations

import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.media_assets import read_mp4_video_size
from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.http import HttpResponse
from core.model_providers.manifest import Role, seed_upper_bound
from core.model_providers.recipe import MediaInput, build_recipe_request, role_field

from default_model_providers_implement.request_builders import prepare_seedvr2_7b_sharp_fp8
from default_model_providers_implement.seedvr2_worker import load, restore_audio
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8 import (
    SeedVR2SevenBSharpFP8Provider,
    SeedVR2UpscaleRequest,
    SeedVR2Video,
)
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8.manifest import MANIFEST
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8.provider import to_request


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        self.calls.append((method, url, json_body))
        return self.responses.pop(0)


def response(status: int, value: dict) -> HttpResponse:
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


def mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


class SeedVR2ProviderTests(unittest.TestCase):
    def test_submit_uses_model_specific_api_and_media_bytes(self) -> None:
        transport = RecordingTransport([response(202, {"job_token": "job-1", "queue_position": 1})])
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        handle = provider.submit(
            SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", mp4_bytes()), seed=7)
        )

        self.assertEqual(handle.external_id, "job-1")
        method, url, payload = transport.calls[0]
        self.assertEqual((method, url), ("POST", "http://models/seedvr2/7b-sharp-fp8/upscales"))
        self.assertEqual(payload["target_short_side"], 720)
        self.assertEqual(payload["max_long_side"], 1280)
        self.assertNotIn("path", json.dumps(payload))

    def test_success_observation_is_normalized(self) -> None:
        transport = RecordingTransport(
            [
                response(
                    200,
                    {
                        "stage": "done",
                        "ratio": 1.0,
                        "description": "完成",
                        "movie": {
                            "key": "job-1",
                            "mime": "video/mp4",
                            "length": 44,
                            "digest": "a" * 64,
                            "duration_seconds": 3.25,
                        },
                    },
                )
            ]
        )
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        observation = provider.observe(ProviderHandle(provider.plugin_id, 1, "job-1"))

        self.assertIs(observation.phase, GenerationPhase.SUCCEEDED)
        self.assertEqual(observation.artifact.media_type, "video/mp4")
        self.assertEqual(observation.artifact.duration_seconds, 3.25)

    def test_observe_rejects_unknown_fields(self) -> None:
        transport = RecordingTransport(
            [response(200, {"stage": "queued", "ratio": 0.0, "description": "等待", "cwd": "x"})]
        )
        provider = SeedVR2SevenBSharpFP8Provider("http://models", transport)

        with self.assertRaises(ModelProviderError):
            provider.observe(ProviderHandle(provider.plugin_id, 1, "job-1"))

    def test_media_boundary_rejects_non_mp4(self) -> None:
        with self.assertRaises(ValueError):
            SeedVR2Video("video/webm", b"bytes")


class SeedVR2PrivateRequestTests(unittest.TestCase):
    def test_builder_writes_only_fixed_input_and_strict_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            task_dir = Path(temporary)
            record = TaskRecord(
                "a" * 32,
                "seedvr2_7b_sharp_fp8",
                "queued",
                0.0,
                "等待模型资源。",
                str(task_dir),
            )
            prepare = prepare_seedvr2_7b_sharp_fp8(
                {
                    "source_video": {"mime": "video/mp4", "base64": "AAAAGGZ0eXBpc29tAAAAAA=="},
                    "target_short_side": 1080,
                    "max_long_side": 1920,
                    "seed": 42,
                }
            )

            prepare(record)
            request = load(task_dir / "request.json")

            self.assertEqual(request["source"], (task_dir / "input.mp4").resolve())
            self.assertEqual(request["target_short_side"], 1080)

    def test_builder_rejects_unknown_or_fake_video(self) -> None:
        with self.assertRaises(RequestError):
            prepare_seedvr2_7b_sharp_fp8(
                {
                    "source_video": {"mime": "video/mp4", "base64": "bm90LW1wNA=="},
                    "target_short_side": 1080,
                    "max_long_side": 1920,
                    "seed": 42,
                    "command": "whoami",
                }
            )

    def test_builder_rejects_seed_beyond_32_bits(self) -> None:
        with self.assertRaises(RequestError):
            prepare_seedvr2_7b_sharp_fp8(
                {
                    "source_video": {"mime": "video/mp4", "base64": "AAAAGGZ0eXBpc29tAAAAAA=="},
                    "target_short_side": 1080,
                    "max_long_side": 1920,
                    "seed": 2**32,
                }
            )


def sized_mp4(width: int, height: int) -> bytes:
    """只含 box 结构、tkhd 声明了显示宽高的 MP4。"""

    def box(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I4s", 8 + len(body), kind) + body

    def full(kind: bytes, body: bytes) -> bytes:
        return box(kind, b"\x00\x00\x00\x00" + body)

    tkhd = full(
        b"tkhd",
        b"\x00" * 8
        + struct.pack(">I", 1)
        + b"\x00" * 60
        + struct.pack(">II", width << 16, height << 16),
    )
    hdlr = full(b"hdlr", b"\x00" * 4 + b"vide" + b"\x00" * 13)
    trak = box(b"trak", tkhd + box(b"mdia", hdlr))
    return box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", trak)


def upscale_request(content: bytes, resolution: str):
    return build_recipe_request(
        MANIFEST,
        "seedvr2_7b_sharp_fp8.upscale",
        inputs={"video": (MediaInput("video/mp4", content),)},
        params={"seed": 1},
        settings={"resolution": resolution},
    )


class SeedVR2ResolutionTierTests(unittest.TestCase):
    def test_reads_declared_display_size(self) -> None:
        self.assertEqual(read_mp4_video_size(sized_mp4(1280, 704)), (1280, 704))
        self.assertIsNone(read_mp4_video_size(mp4_bytes()))

    def test_rejects_source_already_near_target_tier(self) -> None:
        for width, height, tier in (
            (1280, 704, "720p"),
            (704, 1280, "720p"),
            (1920, 1088, "1080p"),
            (1920, 1088, "720p"),
            (1728, 972, "1080p"),
        ):
            with (
                self.subTest(size=(width, height), tier=tier),
                self.assertRaisesRegex(ValueError, "无需超分"),
            ):
                upscale_request(sized_mp4(width, height), tier)

    def test_accepts_source_clearly_below_target_tier(self) -> None:
        for width, height, tier, target in (
            (864, 480, "720p", 720),
            (864, 480, "1080p", 1080),
            (1280, 704, "1080p", 1080),
            (1408, 704, "1080p", 1080),
        ):
            with self.subTest(size=(width, height), tier=tier):
                request = to_request(upscale_request(sized_mp4(width, height), tier))
                self.assertEqual((request.target_short_side, request.max_long_side), (target, 2560))

    def test_unreadable_size_is_left_to_the_model_service(self) -> None:
        self.assertEqual(to_request(upscale_request(mp4_bytes(), "720p")).target_short_side, 720)

    def test_default_tier_is_1080p(self) -> None:
        self.assertEqual(MANIFEST.default_settings(), {"resolution": "1080p"})


class SeedVR2AudioTests(unittest.TestCase):
    """SeedVR2 只输出视频轨；worker 必须把原视频音轨封装回去，否则对白会丢失。"""

    @staticmethod
    def _ffmpeg(*args: str) -> None:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)

    @staticmethod
    def _streams(path: Path) -> list[str]:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0"]
            + [str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.split()

    def _render(self, root: Path, *, with_audio: bool) -> tuple[Path, Path]:
        source = root / "input.mp4"
        video = ["-f", "lavfi", "-i", "color=c=red:s=320x176:r=24:d=1"]
        audio = ["-f", "lavfi", "-i", "sine=frequency=500:duration=1"] if with_audio else []
        self._ffmpeg(*video, *audio, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source))
        return source, root / "output.mp4"

    def test_source_audio_is_restored_without_reencoding_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._render(root, with_audio=True)
            self._ffmpeg(
                "-f", "lavfi", "-i", "color=c=blue:s=640x352:r=24:d=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
            )  # fmt: skip
            video_before = self._video_packets(output)

            restore_audio(source, output)

            self.assertEqual(sorted(self._streams(output)), ["audio", "video"])
            self.assertEqual(self._video_packets(output), video_before)
            self.assertFalse((root / "output.muxed.mp4").exists())

    def test_source_without_audio_keeps_video_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = self._render(root, with_audio=False)
            self._ffmpeg(
                "-f", "lavfi", "-i", "color=c=blue:s=640x352:r=24:d=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
            )  # fmt: skip

            restore_audio(source, output)

            self.assertEqual(self._streams(output), ["video"])

    @staticmethod
    def _video_packets(path: Path) -> str:
        return subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries"]
            + ["packet=size", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout


class SeedVR2ManifestTests(unittest.TestCase):
    def test_recipe_declares_32_bit_seed(self) -> None:
        (recipe,) = MANIFEST.recipes
        seed = role_field(recipe, Role.SEED)

        self.assertEqual(seed_upper_bound(seed), 2**32 - 1)
        self.assertEqual(seed.validate(2**32 - 1), 2**32 - 1)
        with self.assertRaisesRegex(ValueError, "0 到 4294967295"):
            seed.validate(2**32)


if __name__ == "__main__":
    unittest.main()
