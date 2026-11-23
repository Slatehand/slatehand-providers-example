"""Colab 的同步语音转写，只接受 WAV 字节和固定语言选项。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .strict_json import RequestError, encoded_bytes, object_fields, string

MAX_WAV_BYTES = 64 * 1024 * 1024


def transcribe(payload: Any) -> str:
    data = object_fields(payload, required={"audio_b64", "language"})
    language = string(data["language"], "language", maximum=4)
    if language not in {"auto", "zh", "en"}:
        raise RequestError("Whisper 只支持 auto、zh 或 en。")
    audio = encoded_bytes(data["audio_b64"], "audio_b64", maximum=MAX_WAV_BYTES)
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise RequestError("Whisper 只接受 WAV 音频。")

    binary = os.environ.get("SLATEHAND_WHISPER_CLI")
    model = os.environ.get("SLATEHAND_WHISPER_MODEL")
    if not binary or not model or not os.access(binary, os.X_OK) or not Path(model).is_file():
        raise RuntimeError("Colab Whisper 尚未就绪，请等待安装和权重下载完成。")

    with TemporaryDirectory(prefix="slatehand-whisper-") as directory:
        source = Path(directory) / "input.wav"
        pcm = Path(directory) / "pcm.wav"
        output = Path(directory) / "transcription"
        source.write_bytes(audio)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "wav",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(pcm),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            raise RequestError("Whisper 无法解码 WAV 音频。") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Colab Whisper 的音频预处理失败。") from exc
        try:
            subprocess.run(
                [
                    binary,
                    "-m",
                    model,
                    "-f",
                    str(pcm),
                    "-l",
                    language,
                    "-ng",
                    "-nt",
                    "-otxt",
                    "-of",
                    str(output),
                ],
                check=True,
                capture_output=True,
                timeout=480,
            )
            text = output.with_suffix(".txt").read_text(encoding="utf-8").strip()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Colab Whisper 转写失败。") from exc
    if not text or len(text) > 20_000:
        raise RequestError("Whisper 没有返回有效文字。")
    return text
