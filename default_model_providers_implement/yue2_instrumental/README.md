# YuE2 纯音乐转谱

`abc_tools.py`、`compile_score.py`、`common.py`、`instrumentalize.py` 原样取自 YuE2 官方纯音乐 Skill
（`skills/yue2-music/instrumental/scripts/`，MIT，许可证全文见同目录 `LICENSE`），不做修改，也不参与本仓库的 ruff 格式检查。

`yue2_worker.py` 在歌词为空时把本目录加入 `sys.path` 并调用 `instrumentalize.convert_score`：把模型写出的
`Vocal` 声部音符全部移到 `Ins`，`Vocal` 只保留休止与和弦；两声部重叠时人声优先，并校验音高、起点、时值、拍号、
速度与和弦不变。本目录只做纯文本转换，不读写文件、不加载模型。
