"""首次使用专项 LoRA 时按固定版本安装到 ComfyUI 模型目录。"""

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

_URL = (
    "https://huggingface.co/JOKER141/MiniMax-H3-Weapon-Combat-LoRA/resolve/"
    "5979d9fac7937fd2f5204e1613fa508253d856e5/Bunny_weapon_combatV1.safetensors"
)
_SHA256 = "d49de2902f3ea5e6889d9489c031ed64694de93d6a77c111d164f83c0dc359df"
_SIZE = 155110272


def ensure_weight(target: Path) -> None:
    if target.is_file() and target.stat().st_size == _SIZE:
        with target.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == _SHA256:
                return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as output:
        temporary = Path(output.name)
    try:
        digest = hashlib.sha256()
        with urlopen(_URL, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                if output.tell() + len(chunk) > _SIZE:
                    raise ValueError("冷兵器交锋 LoRA 下载大小超出预期。")
                output.write(chunk)
                digest.update(chunk)
        if temporary.stat().st_size != _SIZE or digest.hexdigest() != _SHA256:
            raise ValueError("冷兵器交锋 LoRA 权重校验失败。")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
