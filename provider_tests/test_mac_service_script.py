"""Mac 媒体服务启动脚本的调度 lane 布局。"""

from pathlib import Path

MAC_RUN_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "default_model_providers_implement"
    / "macos"
    / "run_codex_server.sh"
)


def test_mac_provider_script_declares_image_and_audio_lanes() -> None:
    """Mac 服务用 network_image / mac_heavy 两个 lane 启动；ffmpeg 工具在 Core 本机执行。"""
    script = MAC_RUN_SCRIPT.read_text()
    assert (
        "network_image:4:codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit"
        in script
    )
    assert "--lane mac_heavy:1:demucs_audio_separation\n" in script
    assert "ffmpeg_" not in script
    assert "--resource-name" not in script
    assert "--max-concurrent-tasks" not in script
