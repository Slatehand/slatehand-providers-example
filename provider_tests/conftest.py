"""example 测试复用 Slatehand Core 的测试支撑。

把 Core 检出目录的 `tests/` 与根目录（测试支撑用到 `scripts.harness`）加入 import 路径，
并导出 fixture。

Core 默认位于同一工作区的 `../slatehand`；放在别处时用 `SLATEHAND_CORE_DIR` 指定。
"""

import os
import sys
from pathlib import Path

CORE_DIRECTORY = Path(
    os.environ.get("SLATEHAND_CORE_DIR") or Path(__file__).resolve().parents[2] / "slatehand"
)
CORE_TESTS = CORE_DIRECTORY / "tests"
if not (CORE_TESTS / "conftest.py").is_file():
    raise RuntimeError(
        f"找不到 Slatehand Core 的测试支撑：{CORE_TESTS}；"
        "请把 Core 放在 ../slatehand 或设置 SLATEHAND_CORE_DIR。"
    )
for entry in (CORE_DIRECTORY, CORE_TESTS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from conftest import (  # noqa: E402,F401
    http_server,
    journey,
    playground_factory,
    png_bytes,
    service_factory,
    store_factory,
    stories_root,
    synthetic_provider,
    wav_bytes,
)
