from __future__ import annotations

import hashlib
import io
import json
import sys
import threading
import time
import wave
from pathlib import Path

import pytest
from core.director_proposals.professional_contracts import read_contract
from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.http import HttpResponse, UrllibTransport
from core.model_providers.image_prompt_skill import audio_prompt_guide
from core.model_providers.manifest import Capability
from core.model_providers.recipe import build_recipe_request
from core.model_providers.registry import ProviderRegistry
from core.structured_director.reads.professional_worksets import workset_read

from default_model_providers_implement import runners, yue2_worker
from default_model_providers_implement import server as server_module
from default_model_providers_implement.request_builders import prepare_yue2
from default_model_providers_implement.resource_manager import RunResult
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord
from default_model_providers_implement.yue2_worker import load_request
from slatehand_providers.plugins.stable_audio_3.plugin import plugin_instance as stable_audio_plugin
from slatehand_providers.plugins.yue2 import MANIFEST, YuE2Provider, YuE2Request
from slatehand_providers.plugins.yue2.plugin import plugin_instance
from slatehand_providers.plugins.yue2.provider import to_request

TASK = "ab" * 16


class _Transport:
    def __init__(self, status: dict | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.status = status or {
            "stage": "done",
            "progress": 1,
            "message": "歌曲已写好。",
            "audio": {
                "id": TASK,
                "mime": "audio/wav",
                "bytes": 12,
                "sha256": "cd" * 32,
                "duration_seconds": 183.4,
            },
        }

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        del timeout
        self.calls.append((method, url, json_body))
        if method == "POST":
            return HttpResponse(202, {}, json.dumps({"generation_id": TASK}).encode())
        if method == "PUT":
            return HttpResponse(409, {}, b"{}")
        if url.endswith(f"/audio/{TASK}"):
            return HttpResponse(200, {}, b"RIFFwav")
        return HttpResponse(200, {}, json.dumps(self.status).encode())


def _wav(seconds: float = 0.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48000)
        handle.writeframes(b"\x00" * int(48000 * seconds) * 4)
    return buffer.getvalue()


def test_plugin_instance_identity_and_playground_only_capability() -> None:
    instance = plugin_instance("http://windows:8791")
    assert instance.manifest.plugin_id == "yue2"
    [recipe] = MANIFEST.recipes
    assert recipe.id == "yue2.generate"
    assert recipe.capability is Capability.AUDIO_GENERATE
    assert [field.key for field in recipe.params] == ["prompt", "lyrics", "seed"]
    assert recipe.slots == ()


def test_to_request_translates_validated_params_and_allows_empty_lyrics() -> None:
    contract = build_recipe_request(
        MANIFEST,
        "yue2.generate",
        inputs={},
        params={"prompt": "City Pop，女声", "lyrics": "[Verse]\n路灯眨着眼睛", "seed": 7},
    )
    assert to_request(contract) == YuE2Request("City Pop，女声", "[Verse]\n路灯眨着眼睛", 7)
    instrumental = build_recipe_request(
        MANIFEST, "yue2.generate", inputs={}, params={"prompt": "lo-fi", "lyrics": "", "seed": 0}
    )
    assert to_request(instrumental).lyrics == ""


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"prompt": " ", "lyrics": "", "seed": 1}, "不能为空"),
        ({"prompt": "x" * 1001, "lyrics": "", "seed": 1}, "1000"),
        ({"prompt": "pop", "lyrics": "x" * 4001, "seed": 1}, "4000"),
        ({"prompt": "pop", "lyrics": "", "seed": -1}, "Seed"),
        ({"prompt": "pop", "lyrics": "", "seed": 1, "cfg_scale": 1.2}, "参数"),
    ],
)
def test_recipe_rejects_invalid_params(params: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_recipe_request(MANIFEST, "yue2.generate", inputs={}, params=params)


def test_request_dto_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="风格描述"):
        YuE2Request("", "", 1)
    with pytest.raises(ValueError, match="歌词"):
        YuE2Request("pop", "x" * 4001, 1)
    with pytest.raises(ValueError, match="seed"):
        YuE2Request("pop", "", 2**63)
    with pytest.raises(ValueError, match="seed"):
        YuE2Request("pop", "", True)  # type: ignore[arg-type]


def test_provider_submits_closed_body_observes_and_reads_wav() -> None:
    transport = _Transport()
    provider = YuE2Provider("http://windows:8791/", transport)
    handle = provider.submit(YuE2Request("City Pop", "[Chorus]\n今晚不眠", 12300))
    assert handle == ProviderHandle("yue2", 1, TASK)
    assert transport.calls[0] == (
        "POST",
        "http://windows:8791/yue2/generations",
        {"style": "City Pop", "lyrics": "[Chorus]\n今晚不眠", "seed": 12300},
    )
    observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED
    assert observation.artifact is not None
    assert observation.artifact.media_type == "audio/wav"
    assert observation.artifact.duration_seconds == 183.4
    assert provider.read_artifact(handle, TASK) == b"RIFFwav"
    assert transport.calls[-1][1] == f"http://windows:8791/yue2/generations/{TASK}/audio/{TASK}"


@pytest.mark.parametrize(
    ("stage", "phase"),
    [
        ("queued", GenerationPhase.QUEUED),
        ("generating", GenerationPhase.RUNNING),
        ("cancelled", GenerationPhase.CANCELLED),
    ],
)
def test_provider_maps_non_terminal_and_cancelled_stages(stage: str, phase) -> None:
    provider = YuE2Provider(
        "http://w", _Transport({"stage": stage, "progress": 0.1, "message": "排队中"})
    )
    observation = provider.observe(ProviderHandle("yue2", 1, TASK))
    assert observation.phase is phase
    assert observation.artifact is None


def test_provider_maps_failure_with_default_code_and_retryable() -> None:
    provider = YuE2Provider(
        "http://w",
        _Transport({"stage": "failed", "progress": 0.4, "message": "显存不足", "retryable": True}),
    )
    observation = provider.observe(ProviderHandle("yue2", 1, TASK))
    assert observation.phase is GenerationPhase.FAILED
    assert observation.error_code == "song_generation_failed"
    assert observation.retryable is True


def test_provider_rejects_unknown_stage_and_unknown_fields() -> None:
    handle = ProviderHandle("yue2", 1, TASK)
    with pytest.raises(ModelProviderError, match="stage"):
        YuE2Provider("http://w", _Transport({"stage": "x", "progress": 0, "message": ""})).observe(
            handle
        )
    with pytest.raises(ModelProviderError):
        YuE2Provider(
            "http://w",
            _Transport({"stage": "queued", "progress": 0, "message": "", "abc": "X:1"}),
        ).observe(handle)
    with pytest.raises(ModelProviderError, match="audio"):
        YuE2Provider(
            "http://w", _Transport({"stage": "done", "progress": 1, "message": ""})
        ).observe(handle)


def test_provider_cancel_accepts_finished_task_and_rejects_foreign_handles() -> None:
    transport = _Transport()
    provider = YuE2Provider("http://w", transport)
    assert provider.cancel(ProviderHandle("yue2", 1, TASK)).phase is GenerationPhase.SUCCEEDED
    assert transport.calls[0][:2] == ("PUT", f"http://w/yue2/generations/{TASK}/abort")
    for handle in (
        ProviderHandle("stable-audio-3.medium", 1, TASK),
        ProviderHandle("yue2", 2, TASK),
    ):
        with pytest.raises(ModelProviderError, match="YuE2"):
            provider.observe(handle)
        with pytest.raises(ModelProviderError, match="YuE2"):
            provider.read_artifact(handle, TASK)


def test_prepare_writes_closed_request_readable_by_worker(tmp_path: Path) -> None:
    record = TaskRecord(TASK, "yue2", "queued", 0.0, "", str(tmp_path))
    prepare_yue2({"style": "  Ballad  ", "lyrics": "\n[Verse]\n雨\n", "seed": 3})(record)
    written = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert written == {
        "schema": "yue2_request_v1",
        "style": "Ballad",
        "lyrics": "[Verse]\n雨",
        "seed": 3,
    }
    assert load_request(tmp_path / "request.json") == written


def test_prepare_rejects_unknown_missing_and_invalid_fields() -> None:
    with pytest.raises(RequestError, match="未知字段"):
        prepare_yue2({"style": "pop", "lyrics": "", "seed": 3, "cot": "off"})
    with pytest.raises(RequestError):
        prepare_yue2({"style": "pop", "seed": 3})
    with pytest.raises(RequestError, match="style"):
        prepare_yue2({"style": "   ", "lyrics": "", "seed": 3})
    with pytest.raises(RequestError, match="lyrics"):
        prepare_yue2({"style": "pop", "lyrics": "x" * 4001, "seed": 3})
    with pytest.raises(RequestError, match="seed"):
        prepare_yue2({"style": "pop", "lyrics": "", "seed": 2**63})


def test_worker_rejects_foreign_schema_and_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"schema": "stable_audio_3_request_v1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        load_request(path)
    path.write_text(
        json.dumps(
            {"schema": "yue2_request_v1", "style": "pop", "lyrics": "", "seed": 1, "abc": ""}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="字段"):
        load_request(path)


def test_module_runner_carries_worker_summary_into_result(tmp_path: Path) -> None:
    record = TaskRecord(TASK, "yue2", "running", 0.0, "", str(tmp_path))
    (tmp_path / "request.json").write_text("{}", encoding="utf-8")
    script = (
        "import json,pathlib,sys;"
        "print(json.dumps({'event':'progress','value':0.5,'message':'生成中'}),flush=True);"
        "pathlib.Path(sys.argv[1],'output.wav').write_bytes(b'RIFF');"
        "print(json.dumps({'event':'summary','text':'48 kHz 立体声 3.0 秒'}),flush=True)"
    )
    seen: list[tuple[float, str]] = []
    result = runners._module_runner(
        record,
        threading.Event(),
        lambda value, message: seen.append((value, message)),
        module="unused",
        python=sys.executable,
        output_name="output.wav",
        media_type="audio/wav",
        command=[sys.executable, "-c", script, str(tmp_path)],
    )
    assert seen == [(0.5, "生成中")]
    assert result == RunResult(tmp_path / "output.wav", "audio/wav", "48 kHz 立体声 3.0 秒")


def test_service_routes_generation_end_to_end(tmp_path: Path, monkeypatch) -> None:
    wav = _wav()
    submitted: list[dict] = []

    def fake_runner(record, cancel, progress):
        del cancel
        submitted.append(json.loads(Path(record.task_dir, "request.json").read_text("utf-8")))
        progress(0.5, "正在生成歌曲。")
        output = Path(record.task_dir) / "output.wav"
        output.write_bytes(wav)
        return RunResult(output, "audio/wav", "YuE2-3B 48 kHz 立体声 0.5 秒")

    monkeypatch.setattr(server_module, "yue2_runner", fake_runner)
    server = server_module.ModelApiServer(
        ("127.0.0.1", 0), tmp_path / "state", enabled_services={"yue2"}
    )
    server.manager.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        provider = YuE2Provider(f"http://{host}:{port}", UrllibTransport())
        handle = provider.submit(YuE2Request("Ballad", "[Verse]\n雨", 5))
        deadline = time.monotonic() + 30
        observation = provider.observe(handle)
        while observation.phase is not GenerationPhase.SUCCEEDED and time.monotonic() < deadline:
            assert observation.phase in {GenerationPhase.QUEUED, GenerationPhase.RUNNING}
            time.sleep(0.05)
            observation = provider.observe(handle)
        assert observation.phase is GenerationPhase.SUCCEEDED
        assert observation.message.startswith("YuE2-3B 48 kHz 立体声 0.5 秒；生成总用时")
        artifact = observation.artifact
        assert artifact is not None
        assert artifact.duration_seconds == pytest.approx(0.5)
        assert artifact.byte_count == len(wav)
        assert artifact.sha256 == hashlib.sha256(wav).hexdigest()
        assert provider.read_artifact(handle, artifact.artifact_id) == wav
        assert submitted == [
            {"schema": "yue2_request_v1", "style": "Ballad", "lyrics": "[Verse]\n雨", "seed": 5}
        ]
    finally:
        server.shutdown()
        server.manager.shutdown()
        server.server_close()
        thread.join(5)


def test_playground_audio_guide_delivers_skill_only_when_yue2_is_bound() -> None:
    registry = ProviderRegistry()
    registry.install(stable_audio_plugin("http://w"))
    registry.install(plugin_instance("http://w"))
    assert audio_prompt_guide(registry) == {
        "recipe_id": "stable_audio_3.generate",
        "plugin_skills": [],
    }
    registry.bind(Capability.AUDIO_GENERATE.value, "yue2")
    guide = audio_prompt_guide(registry)
    assert guide["recipe_id"] == "yue2.generate"
    [skill] = guide["plugin_skills"]
    assert skill["name"] == "yue2-song-writing"
    [resource] = skill["resources"]
    assert resource["name"] == "SKILL.md"
    assert "name: yue2-song-writing" in resource["text"]
    assert resource["sha256"] == hashlib.sha256(resource["text"].encode()).hexdigest()
    assert audio_prompt_guide(None) == {"recipe_id": None, "plugin_skills": []}


def test_project_song_prompt_contract_carries_bound_audio_plugin_skill_without_workset() -> None:
    registry = ProviderRegistry()
    registry.install(stable_audio_plugin("http://w"))
    registry.install(plugin_instance("http://w"))
    unbound = read_contract("song_prompt", provider_catalog=registry)
    assert [item["name"] for item in unbound["resources"]] == ["SKILL.md"]
    assert unbound["output_schema_source"] is None
    assert "Playground" in unbound["resources"][0]["text"]
    registry.bind(Capability.AUDIO_GENERATE.value, "yue2")
    bound = read_contract("song_prompt", provider_catalog=registry)
    assert [item["name"] for item in bound["resources"]] == [
        "SKILL.md",
        "plugin/yue2-song-writing/SKILL.md",
    ]
    assert "name: yue2-song-writing" in bound["resources"][1]["text"]
    with pytest.raises(ValueError, match="只有契约"):
        workset_read(None, {"capability": "song_prompt", "scope": {}})


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yue2"


def _voices(abc: str):
    tools = str(Path(yue2_worker.__file__).resolve().parent / "yue2_instrumental")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from abc_tools import parse_abc

    return parse_abc(abc).voices


def test_instrumental_score_moves_real_model_vocal_melody_to_ins() -> None:
    source = (FIXTURES / "model_plan_seed42.abc").read_text(encoding="utf-8")
    before = _voices(source)
    assert before["Vocal"].notes, "fixture 必须是带人声旋律的真实模型乐谱"
    prepared = yue2_worker.instrumental_score(source)
    score, lyrics, cot = prepared.score, prepared.lyrics, prepared.cot
    assert prepared.removed_sections == ()
    assert prepared.final_seconds == prepared.planned_seconds < yue2_worker.INSTRUMENTAL_MAX_SECONDS
    after = _voices(score)
    assert after["Vocal"].notes == []
    assert all(note in after["Ins"].notes for note in before["Vocal"].notes)
    assert after["Ins"].bars == before["Ins"].bars
    assert after["Vocal"].chords and cot == "full"
    assert lyrics == "[Intro]\n\n[Verse]\n\n[Interlude]\n\n[Chorus]\n\n[Outro]\n"


def test_instrumental_score_trims_long_real_score_before_its_final_section() -> None:
    source = (FIXTURES / "model_plan_seed4243_long.abc").read_text(encoding="utf-8")
    prepared = yue2_worker.instrumental_score(source)
    assert prepared.planned_seconds > 360 > yue2_worker.INSTRUMENTAL_MAX_SECONDS
    assert prepared.final_seconds <= yue2_worker.INSTRUMENTAL_MAX_SECONDS
    assert len(prepared.removed_sections) == 2
    labels = [line for line in prepared.score.splitlines() if line.startswith("% ")]
    assert labels[0] == "% intro" and labels[-1] == "% chorus"
    assert prepared.lyrics == "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Verse]\n\n[Chorus]\n"
    voices = _voices(prepared.score)
    assert voices["Vocal"].notes == [] and voices["Ins"].notes


def test_fit_instrumental_length_keeps_score_valid_or_untouched() -> None:
    source = (FIXTURES / "model_plan_seed4243_long.abc").read_text(encoding="utf-8")
    converted = yue2_worker.instrumental_score(source).score
    unchanged, removed = yue2_worker.fit_instrumental_length(converted, 10_000)
    assert unchanged == converted and removed == ()
    # 上限低到只剩首尾两段也不够时停止，不删首段与末段，结果仍可被官方解析器接受。
    minimal, removed = yue2_worker.fit_instrumental_length(converted, 1)
    labels = [line for line in minimal.splitlines() if line.startswith("% ")]
    assert labels[0] == "% intro" and labels[-1] == "% chorus"
    assert len(labels) + len(removed) == 5
    _voices(minimal)


class _FakePlan:
    def __init__(self, abc: str | None, truncated: bool = False) -> None:
        self.abc, self.truncated = abc, truncated


class _FakeSemantic:
    tokens = [0] * 50
    truncated = False


class _FakePipeline:
    plans: list[tuple[str, str, dict]] = []
    draft = _FakePlan((FIXTURES / "model_plan_seed42.abc").read_text(encoding="utf-8"))

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def plan(self, style, lyrics, **kwargs):
        kwargs.pop("on_token", None)
        self.plans.append((style, lyrics, kwargs))
        return self.draft if len(self.plans) == 1 and "abc" not in kwargs else _FakePlan(None)

    def generate_semantic(self, plan, **kwargs):
        return _FakeSemantic()

    def synthesize(self, semantic):
        return "latents"

    def decode(self, latents):
        return [[0.0, 0.0]] * 48000


def _run_worker(tmp_path: Path, monkeypatch, lyrics: str, draft=None) -> list[str]:
    import types

    _FakePipeline.plans = []
    if draft is not None:
        monkeypatch.setattr(_FakePipeline, "draft", draft)
    monkeypatch.setitem(sys.modules, "yue2", types.SimpleNamespace(YuE2Pipeline=_FakePipeline))
    written: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "soundfile",
        types.SimpleNamespace(write=lambda path, *a, **k: written.append(path)),
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"schema": "yue2_request_v1", "style": "cello", "lyrics": lyrics, "seed": 9}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["yue2_worker", "--request-file", str(request), "--model-dir", "m", "--vae-dir", "v"],
    )
    assert yue2_worker.main() == 0
    assert written == [str(tmp_path / "output.wav")]
    return [call[1] for call in _FakePipeline.plans]


def test_worker_with_lyrics_plans_once_without_voice_transfer(
    tmp_path, monkeypatch, capsys
) -> None:
    lyrics = "[Verse]\n雨落在旧街"
    assert _run_worker(tmp_path, monkeypatch, lyrics) == [lyrics]
    assert _FakePipeline.plans[0][2] == {"cot": "full", "seed": 9}
    assert "YuE2-3B 歌曲 48 kHz" in capsys.readouterr().out


def test_worker_without_lyrics_renders_transferred_instrumental_score(
    tmp_path, monkeypatch, capsys
) -> None:
    _run_worker(tmp_path, monkeypatch, "")
    (_, planning_lyrics, planning), (_, final_lyrics, final) = _FakePipeline.plans
    assert planning_lyrics == yue2_worker.INSTRUMENTAL_PLANNING_LYRICS
    assert planning == {"cot": "full", "seed": 9}
    assert final_lyrics == "[Intro]\n\n[Verse]\n\n[Interlude]\n\n[Chorus]\n\n[Outro]\n"
    assert final["cot"] == "full" and final["seed"] == 9
    assert _voices(final["abc"])["Vocal"].notes == []
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert "纯音乐（人声旋律已移到器乐声部）" in events[-1]["text"]
    assert "正在把人声旋律移到器乐声部。" in [event.get("message") for event in events]


def test_worker_rejects_truncated_instrumental_plan(tmp_path, monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="截断"):
        _run_worker(tmp_path, monkeypatch, "", draft=_FakePlan("X:1", truncated=True))


def test_worker_reports_trimmed_instrumental_sections(tmp_path, monkeypatch, capsys) -> None:
    long_plan = _FakePlan((FIXTURES / "model_plan_seed4243_long.abc").read_text(encoding="utf-8"))
    _run_worker(tmp_path, monkeypatch, "", draft=long_plan)
    final = _FakePipeline.plans[1][2]
    assert _voices(final["abc"])["Vocal"].notes == []
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])["text"]
    assert "乐谱原长约 392 秒，删去 2 段" in summary and "后约 289 秒" in summary
