# YuE2-3B

Playground 歌曲生成插件。把风格描述、歌词与 seed 提交到私有模型服务的 `/yue2/generations`，观察阶段并取回
48 kHz 立体声 WAV（人声与伴奏混在一条音轨）。项目导演台不注册、不调用 `audio.generate`。

- 风格描述：1 到 1000 字，写曲风、乐器、人声特征、语言与速度；
- 歌词：最多 4000 字，用 `[Verse]`、`[Chorus]` 等段落标签分段，可为空（纯音乐）；为空时模型服务按官方纯音乐流程
  把内部乐谱的人声旋律移到器乐声部、超过 5 分钟时删去中间的重复段落后再生成；
- 没有时长参数：歌曲长度由歌词与模型决定，最长约 6 分钟，达到生成上限时完成消息注明被截断；
- 模型内部先写带和弦的 ABC 乐谱再生成音频，乐谱只在模型服务的任务目录里使用，不回传；
- CFG、采样参数与解码器由模型服务固定为官方默认值，不进入 Core 请求。

随插件发布的 `skills/yue2-song-writing/` 是改写自 YuE2 官方 `yue2-music` 的风格描述与歌词写作 Skill（Apache-2.0，见同目录
`NOTICE`），绑定本插件时经 Playground `playground.list_capabilities` 的 `audio_prompt.plugin_skills` 全文交付，也作为项目专业契约
`song_prompt` 的 `plugin/yue2-song-writing/SKILL.md` 交付给项目 Agent（只写参数，由用户复制到 Playground 生成）。

`manifest.py` 声明参数，`plugin.py` 提供安装工厂，`provider.py` 把 `RecipeRequest` 翻译为本插件 HTTP DTO。
