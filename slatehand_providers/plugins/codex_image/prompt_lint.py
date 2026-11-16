"""Codex 图片提示词软检查：只返回可操作的格式与反模式提示，绝不改写正文或阻止生成。"""

from __future__ import annotations

import re

MAX_RECOMMENDED_CHARS = 850
_PICTURE_LABEL = re.compile(r"<Picture\d+>")
_HEADER_LINE = re.compile(r"^(<[^>\n]+>|图片|第 \d+ 张输入图)\s*[:：]\s*(.*)$")
_PAREN_NEGATION = re.compile(
    r"[（(][^）)\n]*(?:严禁|绝无|禁止|切勿|不得缺失|不做夸张|无扭曲|无畸变)[^）)\n]*[）)]"
)


def lint_codex_image_prompt(recipe_id: str, prompt: str, facts: dict) -> list[str]:
    """按 ``codex_image`` 规范返回中文软提示；空列表表示未发现明显问题。

    ``facts`` 可选包含：
    - ``asset_labels``：实际传入顺序的标签列表（如 ``["<Picture1>", "<Picture2>"]``）；
    - ``inputs_ready``：前置依赖未就绪时为 ``False``，此时跳过实际输入标签核对。
    """
    del recipe_id
    text = prompt.strip()
    if not text:
        return []
    problems: list[str] = []

    if len(text) > MAX_RECOMMENDED_CHARS:
        problems.append(
            f"提示词当前 {len(text)} 字，偏长（建议 ≤ 850 字）："
            "请删减重复的摄影器材套话与修饰语，突出单一视觉重心与静态站位。"
        )
    if "!" in text or "！" in text:
        problems.append(
            "提示词包含感叹号：请改用客观可见的构图、静态姿态与光线陈述，不写情绪化修辞。"
        )
    if _PAREN_NEGATION.search(text):
        problems.append(
            "提示词含括号否定补丁（如结构/解剖禁令）：在句中叠否定句会稀释画面重心；"
            "若候选图畸变或拥挤，请收紧景别、简化前景或退回启动前静止姿态，必要排除项合并为末尾单句。"
        )

    if facts.get("inputs_ready", True) and "asset_labels" in facts:
        expected = list(facts["asset_labels"])
        used = list(dict.fromkeys(_PICTURE_LABEL.findall(text)))
        if not expected:
            if used:
                problems.append(
                    f"当前没有实际参考图输入，但提示词出现了 {'、'.join(used)}；"
                    "无图时请直接写画面正文。"
                )
        else:
            unknown = [label for label in used if label not in expected]
            if unknown:
                problems.append(
                    f"提示词引用了不存在的输入标签 {'、'.join(unknown)}；"
                    f"当前实际输入标签为 {'、'.join(expected)}。"
                )
            lines = text.splitlines()
            if lines and lines[0].strip() in {"图片引用：", "图片引用:"}:
                lines = lines[1:]
            header_ok = len(lines) >= len(expected)
            if header_ok:
                for index, label in enumerate(expected):
                    match = _HEADER_LINE.fullmatch(lines[index].strip())
                    if match is None or match.group(1) != label or not match.group(2).strip():
                        header_ok = False
                        break
            body = "\n".join(lines[len(expected) :]).strip() if header_ok else ""
            for heading in ("画面正文：", "画面正文:"):
                if body.startswith(heading):
                    body = body[len(heading) :].strip()
            if not header_ok or not body or any(label not in body for label in expected):
                problems.append(
                    f"有参考图时须在开头按顺序逐行写 {'、'.join(expected)} 的用途说明，"
                    "并在画面正文中逐一显式引用。"
                )

    return problems
