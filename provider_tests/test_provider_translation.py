"""插件把 Core 提交契约翻译成自家请求。"""

from __future__ import annotations

from core.model_providers.recipe import MediaInput, build_recipe_request

from slatehand_providers.plugins.breeze_tts2 import MANIFEST as BREEZE_MANIFEST
from slatehand_providers.plugins.breeze_tts2 import BreezeTTS2Request, BreezeVoiceReference
from slatehand_providers.plugins.breeze_tts2.provider import to_request as to_breeze
from slatehand_providers.plugins.codex_image import MANIFEST as IMAGE_MANIFEST
from slatehand_providers.plugins.codex_image import (
    CodexImageEditRequest,
    CodexImageGenerateRequest,
    InputImage,
)
from slatehand_providers.plugins.codex_image.provider import to_edit_request, to_generate_request
from slatehand_providers.plugins.demucs_audio import MANIFEST as SEPARATION_MANIFEST
from slatehand_providers.plugins.demucs_audio import DemucsAudioSeparationRequest
from slatehand_providers.plugins.demucs_audio.provider import to_request as to_separation
from slatehand_providers.plugins.minimax_h3.contracts import (
    FL2VARequest,
    KeyframeImage,
    Ref2VARequest,
    ReferenceAudio,
    ReferenceImage,
    ReferenceVideo,
)
from slatehand_providers.plugins.minimax_h3.fl2va import H3KeyframeImage, MiniMaxH3FL2VARequest
from slatehand_providers.plugins.minimax_h3.fl2va.provider import to_request as to_fl2va
from slatehand_providers.plugins.minimax_h3.ref2va import (
    H3ReferenceAudio,
    H3ReferenceFrame,
    H3ReferenceVideo,
    MiniMaxH3Ref2VARequest,
)
from slatehand_providers.plugins.minimax_h3.ref2va.provider import to_request as to_ref2va
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8 import MANIFEST as UPSCALE_MANIFEST
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8 import SeedVR2UpscaleRequest, SeedVR2Video
from slatehand_providers.plugins.seedvr2_7b_sharp_fp8.provider import to_request as to_upscale
from slatehand_providers.plugins.whisper_asr import MANIFEST as ASR_MANIFEST
from slatehand_providers.plugins.whisper_asr import WhisperASRRequest
from slatehand_providers.plugins.whisper_asr.provider import to_request as to_asr

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
_WAV = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 32


def test_translations_match_plugin_requests() -> None:
    generated = build_recipe_request(
        IMAGE_MANIFEST,
        "codex_image.generate",
        inputs={"reference_image": (MediaInput("image/png", _PNG),)},
        params={"prompt": "客厅", "aspect_ratio": "16:9"},
    )
    assert to_generate_request(generated) == (
        CodexImageGenerateRequest("客厅", "16:9", (InputImage("image/png", _PNG),), "gpt-5.6-terra")
    )
    edited = to_edit_request(
        build_recipe_request(
            IMAGE_MANIFEST,
            "codex_image.edit",
            inputs={
                "source_image": (MediaInput("image/png", _PNG),),
                "reference_image": (MediaInput("image/png", _PNG + b"reference"),),
            },
            params={"prompt": "傍晚", "aspect_ratio": "9:16"},
        )
    )
    assert edited == CodexImageEditRequest(
        "傍晚",
        InputImage("image/png", _PNG),
        "9:16",
        (InputImage("image/png", _PNG + b"reference"),),
    )
    clone = build_recipe_request(
        BREEZE_MANIFEST,
        "breeze_tts2.clone",
        inputs={"voice": (MediaInput("audio/wav", _WAV),)},
        params={
            "text": "克隆",
            "reference_transcript": "原文",
            "performance_instruction": "慢",
            "seed": 4,
        },
    )
    assert to_breeze(clone) == BreezeTTS2Request(
        "克隆",
        "慢",
        BreezeVoiceReference("audio/wav", _WAV),
        "原文",
        4.0,
        4,
    )
    design = build_recipe_request(
        BREEZE_MANIFEST,
        "breeze_tts2.voice_design",
        inputs={},
        params={"text": "试音", "voice_description": "低沉", "seed": 9},
    )
    assert to_breeze(design) == BreezeTTS2Request("试音", "低沉", None, None, 4.0, 9)
    assert to_asr(
        build_recipe_request(
            ASR_MANIFEST,
            "whisper_asr.transcribe",
            inputs={"audio": (MediaInput("audio/wav", _WAV),)},
            params={"language": "zh"},
        )
    ) == WhisperASRRequest(_WAV, "audio/wav", "zh")
    frame = KeyframeImage("image/png", _PNG)
    assert to_fl2va(FL2VARequest("船", first_frame=frame, seed=8, save_audio=True)) == (
        MiniMaxH3FL2VARequest(
            "船",
            H3KeyframeImage("image/png", _PNG),
            None,
            832,
            480,
            3.0,
            8,
            20,
            1.0,
            True,
        )
    )
    audio = ReferenceAudio("audio/wav", _WAV)
    picture = ReferenceImage("image/jpeg", b"\xff\xd8\xff" + b"\x00" * 8)
    video_a = ReferenceVideo("video/mp4", _MP4, 2.0)
    video_b = ReferenceVideo("video/mp4", _MP4, 15.0)
    assert to_ref2va(
        Ref2VARequest(
            "房间",
            (audio,),
            last_frame=picture,
            additional_frames=(picture,),
            seed=2,
            reference_videos=(video_a, video_b),
        )
    ) == MiniMaxH3Ref2VARequest(
        "房间",
        (H3ReferenceAudio("audio/wav", _WAV),),
        None,
        H3ReferenceFrame("image/jpeg", picture.content),
        (H3ReferenceFrame("image/jpeg", picture.content),),
        832,
        480,
        3.0,
        2,
        20,
        1.0,
        False,
        (H3ReferenceVideo("video/mp4", _MP4, 2.0), H3ReferenceVideo("video/mp4", _MP4, 15.0)),
    )
    assert to_upscale(
        build_recipe_request(
            UPSCALE_MANIFEST,
            "seedvr2_7b_sharp_fp8.upscale",
            inputs={"video": (MediaInput("video/mp4", _MP4),)},
            params={"seed": 6},
        )
    ) == (SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", _MP4), 1080, 2560, 6))
    assert to_upscale(
        build_recipe_request(
            UPSCALE_MANIFEST,
            "seedvr2_7b_sharp_fp8.upscale",
            inputs={"video": (MediaInput("video/mp4", _MP4),)},
            params={"seed": 6},
            settings={"resolution": "720p"},
        )
    ) == (SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", _MP4), 720, 2560, 6))
    assert to_separation(
        build_recipe_request(
            SEPARATION_MANIFEST,
            "demucs_audio.separate",
            inputs={"video": (MediaInput("video/mp4", _MP4),)},
            params={"stem": "voice"},
        )
    ) == DemucsAudioSeparationRequest(_MP4, "voice")
