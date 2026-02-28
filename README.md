![AstrBot-Logo-Simplified](https://github.com/user-attachments/assets/ffd99b6b-3272-4682-beaa-6fe74250f7d9)

# AstrBot-miaoyimiao

> **⚠ 原项目（Official Upstream）**：[`AstrBotDevs/AstrBot`](https://github.com/AstrBotDevs/AstrBot)
>
> **当前仓库**：`astrbot-miaoyimiao`（基于原项目二次开发，非官方主仓）。

## astrbot-miaoyimiao 特有功能（相对原始仓库）

1. 🧠 长期记忆（LTM）系统：新增 `MemoryEvent/MemoryItem/Evidence` 数据模型、读写策略、维护策略，以及 Dashboard 管理 API 与可视化页面。
2. 🗂️ 项目上下文（Project Context）索引：支持源码符号检索、依赖追踪、架构摘要，以及语义索引构建与检索能力。
   - 结构化解析：`Python(.py/.pyi)`、`JS/TS/Vue(.js/.jsx/.ts/.tsx/.vue)`、`Markdown/RST(.md/.rst)`。
   - 依赖追踪：支持 Python 本地导入与 JS/TS/Vue 本地导入（含相对路径、`@/`、`~/`、`/` 根路径写法）。
   - 路径范围：扫描根目录由索引构建参数决定，默认排除 `.git`、`node_modules`、`dist`、`build`、`venv` 等目录。
   - 范围查询：Dashboard 新增 `GET /api/project_context/scope`，可查看当前支持后缀、排除规则与已索引路径样本。
3. 🛠️ 工程运维（Engineering Ops）中心：集成后台任务观测、工具演进策略预览/应用、编码韧性（resilience）指标与事件快照。
4. 🔁 运行时韧性增强：增加工具循环重试、LLM 失败恢复、流式降级与上下文超限防护策略。
5. 🧩 工作流编辑与部署：新增 Workflow 路由与前端页面，支持工作流保存、测试、多模态输入，以及部署为可用 Provider。
6. 🔌 专业工具预设与后台任务工具：补充 MCP 专业预设与后台任务状态/列表/取消工具，提升可观测与闭环执行能力。
7. 🖼️ Linux Desktop 截图发送可靠性增强：本地 Python 工具新增 `IMAGE_DATA` / `ASTRBOT_IMAGE_OUTPUT` 解析，避免“模型误判已发图”；同时补充截图发送闭环约束（必须收到 `send_message_to_user` 成功回执后才宣称已发送）。

> 差异基线：`git diff upstream/master..master`（当前分支对 `AstrBotDevs/AstrBot` 官方主线）。

### Fork 同步记录

- 2026-02-28：已合并 `upstream/master`（截至 `881b409e`），并保留本 fork 的冲突文件定制逻辑（agent runner / tool exec / live chat / 相关测试）。

### 长期记忆图谱可视化更新（Dashboard）

本仓库新增了长期记忆关系图谱视图，便于从“关系结构”而不是“表格记录”视角审查记忆状态。

- 入口：`Dashboard -> Long-term Memory -> 记忆图谱`
- 交互能力：
  - 支持按 `scope / scope_id / status / predicate / min_confidence / max_relations` 筛选
  - 支持节点与边点击联动，查看关系详情（subject/predicate/object、置信度、状态、关联 memory_id 等）
  - 支持谓词图例与关系密度概览，快速定位热点关系
- 数据来源：`/api/ltm/relations`（图谱展示的是关系层 `memory_relations`，不是 `memory_items` 表格本身）
- 使用说明：
  - 图谱默认主要观察 `active` 关系；若当前只有 `shadow` 记忆，图谱可能为空
  - 关系写入依赖候选事实被激活并同步为 relation；因此历史数据可能需要后续补聊或回填流程才能完全可视化

<div align="center">

<a href="https://github.com/AstrBotDevs/AstrBot/blob/master/README_zh.md">简体中文</a> ｜
<a href="https://github.com/AstrBotDevs/AstrBot/blob/master/README_zh-TW.md">繁體中文</a> ｜
<a href="https://github.com/AstrBotDevs/AstrBot/blob/master/README_ja.md">日本語</a> ｜
<a href="https://github.com/AstrBotDevs/AstrBot/blob/master/README_fr.md">Français</a> ｜
<a href="https://github.com/AstrBotDevs/AstrBot/blob/master/README_ru.md">Русский</a>

<br>

<div>
<a href="https://trendshift.io/repositories/12875" target="_blank"><img src="https://trendshift.io/api/badge/repositories/12875" alt="Soulter%2FAstrBot | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
<a href="https://hellogithub.com/repository/AstrBotDevs/AstrBot" target="_blank"><img src="https://api.hellogithub.com/v1/widgets/recommend.svg?rid=d127d50cd5e54c5382328acc3bb25483&claim_uid=ZO9by7qCXgSd6Lp&t=2" alt="Featured｜HelloGitHub" style="width: 250px; height: 54px;" width="250" height="54" /></a>
</div>

<br>

<div>
<img src="https://img.shields.io/github/v/release/AstrBotDevs/AstrBot?color=76bad9" href="https://github.com/AstrBotDevs/AstrBot/releases/latest">
<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="python">
<img src="https://deepwiki.com/badge.svg" href="https://deepwiki.com/AstrBotDevs/AstrBot">
<a href="https://zread.ai/AstrBotDevs/AstrBot" target="_blank"><img src="https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff" alt="zread"/></a>
<a href="https://hub.docker.com/r/soulter/astrbot"><img alt="Docker pull" src="https://img.shields.io/docker/pulls/soulter/astrbot.svg?color=76bad9"/></a>
<img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.soulter.top%2Fastrbot%2Fplugin-num&query=%24.result&suffix=%20plugins&label=Marketplace&cacheSeconds=3600">
<img src="https://gitcode.com/Soulter/AstrBot/star/badge.svg" href="https://gitcode.com/Soulter/AstrBot">
</div>

<br>

<a href="https://astrbot.app/">Documentation</a> ｜
<a href="https://blog.astrbot.app/">Blog</a> ｜
<a href="https://astrbot.featurebase.app/roadmap">Roadmap</a> ｜
<a href="https://github.com/AstrBotDevs/AstrBot/issues">Issue Tracker</a>
</div>

AstrBot is an open-source all-in-one Agent chatbot platform that integrates with mainstream instant messaging apps. It provides reliable and scalable conversational AI infrastructure for individuals, developers, and teams. Whether you're building a personal AI companion, intelligent customer service, automation assistant, or enterprise knowledge base, AstrBot enables you to quickly build production-ready AI applications within your IM platform workflows.

![screenshot_1 5x_postspark_2026-02-27_22-37-45](https://github.com/user-attachments/assets/f17cdb90-52d7-4773-be2e-ff64b566af6b)

## Key Features

1. 💯 Free & Open Source.
2. ✨ AI LLM Conversations, Multimodal, Agent, MCP, Skills, Knowledge Base, Persona Settings, Auto Context Compression.
3. 🤖 Supports integration with Dify, Alibaba Cloud Bailian, Coze, and other agent platforms.
4. 🌐 Multi-Platform: QQ, WeChat Work, Feishu, DingTalk, WeChat Official Accounts, Telegram, Slack, and [more](#supported-messaging-platforms).
5. 📦 Plugin Extensions with 1000+ plugins available for one-click installation.
6. 🛡️ [Agent Sandbox](https://docs.astrbot.app/use/astrbot-agent-sandbox.html) for isolated, safe execution of code, shell calls, and session-level resource reuse.
7. 💻 WebUI Support.
8. 🌈 Web ChatUI Support with built-in agent sandbox and web search.
9. 🌐 Internationalization (i18n) Support.

<br>

<table align="center">
  <tr align="center">
    <th>💙 Role-playing & Emotional Companionship</th>
    <th>✨ Proactive Agent</th>
    <th>🚀 General Agentic Capabilities</th>
    <th>🧩 1000+ Community Plugins</th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img width="984" height="1746" alt="99b587c5d35eea09d84f33e6cf6cfd4f" src="https://github.com/user-attachments/assets/89196061-3290-458d-b51f-afa178049f84" /></p></td>
    <td align="center"><p align="center"><img width="976" height="1612" alt="c449acd838c41d0915cc08a3824025b1" src="https://github.com/user-attachments/assets/f75368b4-e022-41dc-a9e0-131c3e73e32e" /></p></td>
    <td align="center"><p align="center"><img width="974" height="1732" alt="image" src="https://github.com/user-attachments/assets/e22a3968-87d7-4708-a7cd-e7f198c7c32e" /></p></td>
    <td align="center"><p align="center"><img width="976" height="1734" alt="image" src="https://github.com/user-attachments/assets/0952b395-6b4a-432a-8a50-c294b7f89750" /></p></td>
  </tr>
</table>

## Quick Start

### One-Click Deployment

```bash
uv tool install astrbot
astrbot
```

> Requires [uv](https://docs.astral.sh/uv/) to be installed.

### Docker Deployment

We recommend deploying AstrBot using Docker / Docker Compose.

Please refer to the official documentation: [Deploy AstrBot with Docker](https://astrbot.app/deploy/astrbot/docker.html#%E4%BD%BF%E7%94%A8-docker-%E9%83%A8%E7%BD%B2-astrbot).

### Deploy on RainYun

AstrBot has been officially listed on RainYun's cloud application platform with one-click deployment.

[![Deploy on RainYun](https://rainyun-apps.cn-nb1.rains3.com/materials/deploy-on-rainyun-en.svg)](https://app.rainyun.com/apps/rca/store/5994?ref=NjU1ODg0)

### Desktop Application (Tauri)

Desktop repository: [AstrBot-desktop](https://github.com/AstrBotDevs/AstrBot-desktop).

Supports multiple system architectures, direct package installation, and out-of-the-box usage. A convenient one-click desktop deployment option for beginners.

### One-Click Launcher Deployment (AstrBot Launcher)

A quick deployment and multi-instance solution with environment isolation. Visit the [AstrBot Launcher](https://github.com/Raven95676/astrbot-launcher) repository and install the package for your OS from the latest release.

### Deploy on Replit

Community-contributed deployment method.

[![Run on Repl.it](https://repl.it/badge/github/AstrBotDevs/AstrBot)](https://repl.it/github/AstrBotDevs/AstrBot)

### AUR

```bash
yay -S astrbot-git
```

**More deployment methods**: [BT-Panel Deployment](https://astrbot.app/deploy/astrbot/btpanel.html) | [1Panel Deployment](https://astrbot.app/deploy/astrbot/1panel.html) | [CasaOS Deployment](https://astrbot.app/deploy/astrbot/casaos.html) | [Manual Deployment](https://astrbot.app/deploy/astrbot/cli.html)

## Supported Messaging Platforms

Connect AstrBot to your favorite chat platform.

| Platform | Maintainer |
|---------|---------------|
| QQ | Official |
| OneBot v11 protocol implementation | Official |
| Telegram | Official |
| Wecom & Wecom AI Bot | Official |
| WeChat Official Accounts | Official |
| Feishu (Lark) | Official |
| DingTalk | Official |
| Slack | Official |
| Discord | Official |
| LINE | Official |
| Satori | Official |
| Misskey | Official |
| WhatsApp (Coming Soon) | Official |
| [Matrix](https://github.com/stevessr/astrbot_plugin_matrix_adapter) | Community |
| [KOOK](https://github.com/wuyan1003/astrbot_plugin_kook_adapter) | Community |
| [VoceChat](https://github.com/HikariFroya/astrbot_plugin_vocechat) | Community |

## Supported Model Services

| Service | Type |
|---------|---------------|
| OpenAI and Compatible Services | LLM Services |
| Anthropic | LLM Services |
| Google Gemini | LLM Services |
| Moonshot AI | LLM Services |
| Zhipu AI | LLM Services |
| DeepSeek | LLM Services |
| Ollama (Self-hosted) | LLM Services |
| LM Studio (Self-hosted) | LLM Services |
| [CompShare](https://www.compshare.cn/?ytag=GPU_YY-gh_astrbot&referral_code=FV7DcGowN4hB5UuXKgpE74) | LLM Services |
| [302.AI](https://share.302.ai/rr1M3l) | LLM Services |
| [TokenPony](https://www.tokenpony.cn/3YPyf) | LLM Services |
| [SiliconFlow](https://docs.siliconflow.cn/cn/usercases/use-siliconcloud-in-astrbot) | LLM Services |
| [PPIO Cloud](https://ppio.com/user/register?invited_by=AIOONE) | LLM Services |
| ModelScope | LLM Services |
| OneAPI | LLM Services |
| Dify | LLMOps Platforms |
| Alibaba Cloud Bailian Applications | LLMOps Platforms |
| Coze | LLMOps Platforms |
| OpenAI Whisper | Speech-to-Text Services |
| SenseVoice | Speech-to-Text Services |
| OpenAI TTS | Text-to-Speech Services |
| Gemini TTS | Text-to-Speech Services |
| GPT-Sovits-Inference | Text-to-Speech Services |
| GPT-Sovits | Text-to-Speech Services |
| FishAudio | Text-to-Speech Services |
| Edge TTS | Text-to-Speech Services |
| Alibaba Cloud Bailian TTS | Text-to-Speech Services |
| Azure TTS | Text-to-Speech Services |
| Minimax TTS | Text-to-Speech Services |
| Volcano Engine TTS | Text-to-Speech Services |

## ❤️ Contributing

Issues and Pull Requests are always welcome! Feel free to submit your changes to this project :)

### How to Contribute

You can contribute by reviewing issues or helping with pull request reviews. Any issues or PRs are welcome to encourage community participation. Of course, these are just suggestions—you can contribute in any way you like. For adding new features, please discuss through an Issue first.

### Development Environment

AstrBot uses `ruff` for code formatting and linting.

```bash
git clone https://github.com/AstrBotDevs/AstrBot
pip install pre-commit
pre-commit install
```

## 🌍 Community

### QQ Groups

- Group 1: 322154837
- Group 3: 630166526
- Group 5: 822130018
- Group 6: 753075035
- Group 7: 743746109
- Group 8: 1030353265
- Developer Group: 975206796

### Discord Server

<a href="https://discord.gg/hAVk6tgV36"><img alt="Discord_community" src="https://img.shields.io/badge/Discord-AstrBot-purple?style=for-the-badge&color=76bad9"></a>

## ❤️ Special Thanks

Special thanks to all Contributors and plugin developers for their contributions to AstrBot ❤️

<a href="https://github.com/AstrBotDevs/AstrBot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=AstrBotDevs/AstrBot&max=200&columns=14" />
</a>

Additionally, the birth of this project would not have been possible without the help of the following open-source projects:

- [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) - The amazing cat framework

## ⭐ Star History

> [!TIP]
> If this project has helped you in your life or work, or if you're interested in its future development, please give the project a Star. It's the driving force behind maintaining this open-source project <3

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=astrbotdevs/astrbot&type=Date)](https://star-history.com/#astrbotdevs/astrbot&Date)

</div>

<div align="center">

_Companionship and capability should never be at odds. What we aim to create is a robot that can understand emotions, provide genuine companionship, and reliably accomplish tasks._

_私は、高性能ですから!_

<img src="https://files.astrbot.app/watashiwa-koseino-desukara.gif" width="100"/>
</div>
