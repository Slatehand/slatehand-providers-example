"""一次性 HunyuanVideo-Foley XXL 推理。"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from contextlib import redirect_stdout
from pathlib import Path

WEIGHTS = ("hunyuanvideo_foley.pth", "synchformer_state_dict.pth", "vae_128d_48k.pth")


def progress(value: float, message: str) -> None:
    print(json.dumps({"event": "progress", "value": value, "message": message}), flush=True)


def infer(request_file: Path, repository: Path, models: Path, hf_home: Path | None) -> None:
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if request.get("schema") != "hunyuan_foley_request_v1":
        raise ValueError("视频音效 request schema 不受支持。")
    config = repository / "configs" / "hunyuanvideo-foley-xxl.yaml"
    if not config.is_file() or any(not (models / name).is_file() for name in WEIGHTS):
        raise RuntimeError("HunyuanVideo-Foley XXL 部署尚未就绪，请检查模型与配置。")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    if hf_home is not None:
        os.environ["HF_HOME"] = str(hf_home)
    sys.path.insert(0, str(repository))
    source = request_file.with_name("input.mp4")
    progress(0.05, "正在加载 HunyuanVideo-Foley XXL。")
    with redirect_stdout(sys.stderr):
        import av
        import numpy as np
        import soundfile
        import torch
        from hunyuanvideo_foley import denoise_process, feature_process, load_model

        with av.open(str(source)) as container:
            stream = next(iter(container.streams.video), None)
            if stream is None or stream.duration is None or stream.time_base is None:
                raise ValueError("无法读取来源视频的画面时长。")
            duration = float(stream.duration * stream.time_base)
        if not 1 <= duration <= 15:
            raise ValueError("视频音效只接受 1 至 15 秒的画面。")
        if not torch.cuda.is_available():
            raise RuntimeError("HunyuanVideo-Foley XXL 需要 CUDA。")
        seed = request["seed"]
        random.seed(seed)
        np.random.seed(seed % 2**32)
        torch.manual_seed(seed)
        model, cfg = load_model(
            str(models), str(config), torch.device("cuda:0"), enable_offload=True, model_size="xxl"
        )

    progress(0.15, "正在提取画面和音效描述特征。")
    with redirect_stdout(sys.stderr):
        visual, text, audio_length = feature_process(str(source), request["prompt"], model, cfg)

    progress(0.35, "正在生成同步音效（50 步）。")
    with redirect_stdout(sys.stderr):
        audio, sample_rate = denoise_process(visual, text, audio_length, model, cfg)
    if sample_rate != 48000 or audio.ndim != 3 or audio.shape[:2] != (1, 1) or not audio.shape[2]:
        raise RuntimeError("HunyuanVideo-Foley XXL 输出的音频规格异常。")
    samples = audio[0, 0].numpy()
    frames = round(duration * sample_rate)
    # 上游按 25 fps 视觉帧与 VAE hop 计算样本数，补齐或裁掉末尾的舍入差。
    samples = samples[:frames]
    if len(samples) < frames:
        samples = np.pad(samples, (0, frames - len(samples)))
    pending = request_file.with_name("output.part.wav")
    soundfile.write(pending, samples, sample_rate, subtype="PCM_16")
    pending.replace(request_file.with_name("output.wav"))
    progress(1.0, "已写入 48 kHz 单声道音效。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--hf-home", type=Path)
    args = parser.parse_args()
    try:
        infer(args.request_file, args.repository, args.models, args.hf_home)
    except Exception as exc:
        print(json.dumps({"event": "error", "message": str(exc)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
