# HunyuanVideo-Foley XXL

`audio.foley` 的 `hunyuan_foley.generate` recipe 在 Playground 将一条 1–15 秒 MP4 和音效描述转换成独立的
48 kHz 单声道 WAV。视频上限 512 MiB，音效描述 1–1000 字，seed 为非负 63 位整数。

插件使用 `/hunyuan-foley/generations` 提交、查询、取消和读取 WAV。Windows WSL 与 Colab 使用同一套 XXL
模型服务，通过节点的 Bearer Token 认证。切换「运行节点」影响新提交，已有任务仍经原节点查询。
