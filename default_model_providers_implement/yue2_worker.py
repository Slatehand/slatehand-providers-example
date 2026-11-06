"""YuE2-3B 一次性歌曲生成。由 Windows 模型服务通过 WSL 调用。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

STYLE_MAX = 1000
LYRICS_MAX = 4000
CODEC_HZ = 25
# 官方纯音乐流程的写谱用歌词：只有段落标签，只影响乐谱结构，不会被唱出。
INSTRUMENTAL_PLANNING_LYRICS = "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Outro]\n"
_INSTRUMENTAL_TOOLS = Path(__file__).resolve().parent / "yue2_instrumental"
# 纯音乐乐谱的记谱时长上限：超过时从末尾前按整段删去重复，留出生成上限（约 360 秒）的余量。
INSTRUMENTAL_MAX_SECONDS = 300


@dataclass(frozen=True)
class InstrumentalScore:
    score: str
    lyrics: str
    cot: str
    planned_seconds: float
    final_seconds: float
    removed_sections: tuple[str, ...]


def load_request(path: Path) -> dict[str, object]:
    request = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(request, dict) or request.get("schema") != "yue2_request_v1":
        raise ValueError("YuE2 request schema 不受支持。")
    if set(request) != {"schema", "style", "lyrics", "seed"}:
        raise ValueError("YuE2 request 字段不合法。")
    style, lyrics, seed = request["style"], request["lyrics"], request["seed"]
    if not isinstance(style, str) or not style.strip() or len(style) > STYLE_MAX:
        raise ValueError("style 不合法。")
    if not isinstance(lyrics, str) or len(lyrics) > LYRICS_MAX:
        raise ValueError("lyrics 不合法。")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError("seed 不合法。")
    return request


def _instrumental_tools():
    if str(_INSTRUMENTAL_TOOLS) not in sys.path:
        sys.path.insert(0, str(_INSTRUMENTAL_TOOLS))
    from abc_tools import parse_abc
    from instrumentalize import convert_score

    return parse_abc, convert_score


def _nominal_seconds(score: str) -> float:
    parse_abc, _convert = _instrumental_tools()
    parsed = parse_abc(score)
    return float(parsed.voices["Vocal"].time * 60 / parsed.bpm)


def fit_instrumental_length(score: str, limit: float) -> tuple[str, tuple[str, ...]]:
    """记谱时长超过 limit 时，保留首段与末段，从末段之前逐段删去整段，直到不超过 limit。

    只删不含调号、拍号或速度变化的段落；删后必须仍能被官方解析器接受（连音不跨入不同音高或休止）。
    无法再删时原样返回已删结果。
    """
    parse_abc, _convert = _instrumental_tools()
    header, *blocks = score.split("\n% ")
    removed: list[str] = []

    def join(parts: list[str]) -> str:
        return header + "".join("\n% " + part for part in parts)

    while _nominal_seconds(join(blocks)) > limit:
        for index in range(len(blocks) - 2, 0, -1):
            if any(line[:2] in {"K:", "M:", "Q:"} for line in blocks[index].splitlines()):
                continue
            candidate = blocks[:index] + blocks[index + 1 :]
            try:
                parse_abc(join(candidate))
            except ValueError:
                continue
            removed.append(blocks[index].splitlines()[0])
            blocks = candidate
            break
        else:
            break
    return join(blocks), tuple(removed)


def instrumental_score(abc: str) -> InstrumentalScore:
    """把模型乐谱的人声旋律移到器乐声部并收住长度，给出最终歌词（只有段落标签）与 cot。

    转换与校验由官方 ``instrumentalize.convert_score`` 完成；歌词与 cot 的取法与官方纯音乐流程一致。
    """
    parse_abc, convert_score = _instrumental_tools()
    converted, _check = convert_score(abc, overlap="vocal", keep_chords=True)
    planned = _nominal_seconds(converted)
    score, removed = fit_instrumental_length(converted, INSTRUMENTAL_MAX_SECONDS)
    labels = [line[2:] for line in score.splitlines() if line.startswith("% ")]
    lyrics = "\n\n".join(f"[{label.title()}]" for label in labels) + ("\n" if labels else "")
    cot = "full" if parse_abc(score).voices["Vocal"].chords else "melody"
    return InstrumentalScore(score, lyrics, cot, planned, _nominal_seconds(score), removed)


def _emit(value: float, message: str) -> None:
    print(json.dumps({"event": "progress", "value": value, "message": message}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--vae-dir", type=Path, required=True)
    args = parser.parse_args()
    request = load_request(args.request_file)
    root = args.request_file.parent
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    _emit(0.02, "正在加载 YuE2。")
    import soundfile
    from yue2 import YuE2Pipeline

    started = time.perf_counter()
    pipe = YuE2Pipeline(args.model_dir, args.vae_dir, device="cuda", progress=False)
    loaded = time.perf_counter()
    style, lyrics, seed = str(request["style"]), str(request["lyrics"]), int(request["seed"])
    counts = {"abc": 0, "semantic": 0}

    def on_token(phase: str, _token: int) -> None:
        counts[phase] = counts.get(phase, 0) + 1
        count = counts[phase]
        if count % 250:
            return
        if phase == "abc":
            _emit(0.08, f"正在写内部乐谱：{count} tokens。")
        else:
            _emit(0.15, f"正在生成歌曲：约 {count / CODEC_HZ:.0f} 秒。")

    instrumental = not lyrics.strip()
    prepared: InstrumentalScore | None = None
    with pipe:
        _emit(0.05, "正在写内部乐谱。")
        if instrumental:
            draft = pipe.plan(
                style, INSTRUMENTAL_PLANNING_LYRICS, cot="full", seed=seed, on_token=on_token
            )
            if draft.truncated or not draft.abc:
                raise RuntimeError("YuE2 写出的乐谱为空或被截断，换一个 seed 重试。")
            _emit(0.1, "正在把人声旋律移到器乐声部。")
            prepared = instrumental_score(draft.abc)
            lyrics = prepared.lyrics
            plan = pipe.plan(style, lyrics, cot=prepared.cot, seed=seed, abc=prepared.score)
        else:
            plan = pipe.plan(style, lyrics, cot="full", seed=seed, on_token=on_token)
        _emit(0.12, "正在生成歌曲。")
        semantic = pipe.generate_semantic(plan, on_token=on_token)
        seconds = len(semantic.tokens) / CODEC_HZ
        _emit(0.6, f"正在合成声学细节：约 {seconds:.0f} 秒。")
        latents = pipe.synthesize(semantic)
        _emit(0.9, "正在解码音频。")
        audio = pipe.decode(latents)
    soundfile.write(str(root / "output.wav"), audio, 48000, subtype="PCM_16")
    truncated = plan.truncated or semantic.truncated
    note = "，生成长度达到上限被截断" if truncated else ""
    if prepared is not None and prepared.removed_sections:
        sections = prepared.removed_sections
        note += (
            f"，乐谱原长约 {prepared.planned_seconds:.0f} 秒，删去 {len(sections)} 段"
            f"（{'、'.join(sections)}）后约 {prepared.final_seconds:.0f} 秒"
        )
    _emit(1.0, "歌曲已写好。")
    print(
        json.dumps(
            {
                "event": "summary",
                "text": f"YuE2-3B {'纯音乐（人声旋律已移到器乐声部）' if instrumental else '歌曲'}"
                f" 48 kHz 立体声 {len(audio) / 48000:.1f} 秒{note}"
                f"，权重校验 {loaded - started:.0f} 秒",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"event": "error", "message": str(exc)}), flush=True)
        sys.exit(1)
