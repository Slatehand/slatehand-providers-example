# Slatehand Provider Example 协作说明

本仓库是 [Slatehand Core](https://github.com/Slatehand/slatehand) 的一套 Provider 实现：Core 侧插件、bundle、
随 Core 启停的部署服务，以及 Mac / Windows 上的模型服务。先读 [README](README.md) 与
[模型服务 README](default_model_providers_implement/README.md)。

## 边界

- `slatehand_providers/` 只 import 标准库与 Core 的 Provider SDK（`core.model_providers.*` 等，白名单见
  `provider_tests/test_provider_boundary.py`）；不得依赖 Core 的领域、存储或服务端模块。
- `default_model_providers_implement/` 独立运行，不 import Core 或 `slatehand_providers`。
- 外部模型服务不接收项目语义、任意文件路径、Shell、eval、任意 URL 或任意模型路径。
- Windows、CUDA、盘符、SMB 与模型安装细节只留在本仓库，不进入 Core 的共享协议。
- 插件需要的 Core 能力缺失时，在 Core 仓库扩展 Provider SDK，不在这里绕过。

## 本机与远端部署

- 部署地址、SSH 别名、Windows 路径写在 Git 忽略的 `provider.local.env`；Token 只放 `var/secrets/`。
  不得把 SSH 私钥、SMB 密码、Provider Token、内网地址或个人路径写进仓库。
- LAN HTTP 服务必须绑定指定地址并认证；Token 只保存在忽略的本机状态目录。

## 工程门禁

- `./scripts/check.sh`（`--full` 含 slow）：ruff format/check、pytest 与 `git diff --check`。
  测试复用同一工作区 `../slatehand` 的测试支撑。
- 插件行为变化同步 `provider_tests/README.md` 的规则表；改变线上请求时重录黄金请求并在提交里说明。
- 文档只写现状；施工记录放 Git 忽略的 `wip/`。

## 语言与第三方内容

- 说明、错误与审核文本用中文；API 字段、JSON key 与代码标识符用英文。
- 引入或修改第三方材料时同步登记 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，按上游许可证附带协议全文与修改说明。
