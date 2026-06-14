# AstraBot + Unified Gateway

> 本分支 (`feat/unified-gateway`) 在 AstraBot 基础上新增了**统一网关**能力，使其可作为一个纯粹的多 IM 接入层，将 AI 处理完全外包给外部 Agent 系统。

---

## 一句话定位

**AstraBot = 18+ 主流 IM 平台的接入器 + 统一消息网关**

AstraBot 原生是一个 All-in-One AI 助手，内置 LLM、Agent、知识库、插件等重型模块。但如果你只需要一个**纯粹的消息网关**：接收来自 QQ、Telegram、微信、飞书、钉钉等平台的用户消息，转发给外部 Agent（如 Hermes、Dify、Coze、自研 Agent）处理，再把回复发回去——这个分支就是为此而生的。

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        外部 Agent 系统                        │
│              (Hermes / Dify / Coze / 自研 Agent)              │
└──────────────────┬────────────────────────────┬─────────────┘
                   │                            │
         ┌─────────▼──────────┐      ┌──────────▼──────────┐
         │   Webhook (推送)   │      │  Long Poll (拉取)   │
         │  HTTP POST 推送    │      │  GET /events 拉取    │
         └─────────┬──────────┘      └──────────┬──────────┘
                   │                            │
         ┌─────────▼────────────────────────────▼──────────┐
         │           WebSocket (全双工实时)                 │
         │         WS /api/gateway/stream                 │
         └──────────────────┬─────────────────────────────┘
                            │
         ┌──────────────────▼─────────────────────────────┐
         │           AstraBot 统一网关层                   │
         │  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
         │  │  Gateway │  │  Pipeline│  │  EventBus│    │
         │  │Dispatcher│  │ (轻量)   │  │ (队列)   │    │
         │  └──────────┘  └──────────┘  └──────────┘    │
         └──────────────────┬─────────────────────────────┘
                            │
         ┌──────────────────┼────────────────────────────────────┐
         │                  │                                    │
   ┌─────▼─────┐    ┌───────▼──────┐   ┌──────────┐   ┌────────▼────┐
   │ Telegram  │    │ QQ (OneBot)  │   │  飞书    │   │   钉钉      │
   │           │    │ QQ (官方)    │   │  企业微信 │   │   Discord   │
   └───────────┘    └──────────────┘   └──────────┘   └─────────────┘
   ┌───────────┐    ┌──────────────┐   ┌──────────┐   ┌─────────────┐
   │  Slack    │    │  KOOK        │   │ Misskey  │   │  Satori     │
   │  LINE     │    │  Mattermost  │   │  VoceChat│   │  微信客服   │
   └───────────┘    └──────────────┘   └──────────┘   └─────────────┘
```

**回发通道**（统一）：外部 Agent 处理完后，通过 `POST /api/v1/im/message` 将消息发回指定会话，AstraBot 负责投递到对应 IM 平台。

---

## 核心能力（本分支新增）

| 能力 | 说明 |
|------|------|
| **统一消息信封** | 所有 IM 平台的消息被序列化为标准化的 `MessageEnvelope`，包含 `event_id`、`platform`、`session`、`sender`、`message` 五元组 |
| **Webhook 推送** | AstraBot 收到消息后，立即 HTTP POST 到外部 Agent 的 Webhook URL。适合云端 Agent、微服务架构 |
| **Long Polling 拉取** | 外部 Agent 通过 `GET /api/gateway/events` 阻塞拉取消息。适合本地 Agent、防火墙后部署 |
| **WebSocket 全双工** | 一条连接实时双向收发。适合高频交互、流式回复场景 |
| **统一回发** | 无论通过哪种上行通道接收消息，外部 Agent 都通过 `POST /api/v1/im/message` 回发，路由到正确的 IM 平台与会话 |
| **平台过滤** | Webhook 端点可按平台名称过滤（如只转发 Telegram 和微信） |
| **ACK 防重** | Long Polling 支持 ACK 确认，防止 Agent 崩溃后重复处理 |
| **插件兼容** | 本地插件（关键词过滤、黑名单、速率限制等）仍然生效，优先级高于网关转发 |

---

## 快速开始

### 1. 克隆本分支

```bash
git clone https://github.com/<your-fork>/AstrBot.git
cd AstrBot
git checkout feat/unified-gateway
```

### 2. 配置网关

编辑 `data/cmd_config.json`，新增 `gateway` 段：

```json
{
  "gateway": {
    "enabled": true,
    "message_ttl_seconds": 300,
    "max_queue_size": 10000,
    "channels": {
      "webhook": {
        "enabled": true,
        "endpoints": [
          {
            "name": "hermes-agent",
            "url": "http://hermes-service:8080/astrbot/events",
            "secret": "your-shared-secret",
            "timeout": 30,
            "filter": {
              "platforms": ["telegram", "wecom"]
            }
          }
        ]
      },
      "longpoll": {
        "enabled": true,
        "max_queue_size": 10000,
        "max_unacked": 1000,
        "ack_timeout_seconds": 60
      },
      "websocket": {
        "enabled": true,
        "max_connections_per_key": 3,
        "heartbeat_interval_seconds": 30
      }
    }
  },
  "provider_settings": {
    "enable": false
  }
}
```

### 3. 创建 API Key

在 Dashboard → 扩展 → API Key 管理中创建新 Key：
- **Scope**: 勾选 `im` + `gateway`
- 复制生成的 `abk_xxx` 密钥，供外部 Agent 使用

### 4. 启动

```bash
uv run main.py
```

---

## 三种通道对比

| 维度 | Webhook | Long Polling | WebSocket |
|------|---------|-------------|-----------|
| **方向** | AstraBot → Agent（推送） | Agent → AstraBot（拉取） | 双向 |
| **网络要求** | Agent 需暴露 HTTP 接口 | Agent 无需暴露端口 | 双向可达 |
| **实时性** | 高（即时推送） | 中（取决于 poll 间隔） | 高（实时双向） |
| **断线恢复** | 简单（HTTP 重试） | 简单（续 poll） | 需心跳 + 重连 |
| **适用场景** | 云端 Agent、微服务 | 本地 Agent、防火墙后 | 高频交互、流式回复 |
| **推荐** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |

> 可以同时启用三种通道，不同的 Agent 按需接入。

---

## 项目结构

```
AstrBot/
├── astrbot/
│   ├── core/
│   │   ├── gateway/                  # ⭐ 新增：统一网关核心
│   │   │   ├── envelope.py           # 消息信封 schema
│   │   │   ├── serializer.py         # 消息序列化
│   │   │   ├── dispatcher.py         # 多路分发器
│   │   │   ├── webhook.py            # Webhook 推送
│   │   │   ├── longpoll.py           # Long Polling 队列
│   │   │   └── websocket.py          # WebSocket 连接管理
│   │   ├── pipeline/
│   │   │   └── process_stage/stage.py # 嫁接 Gateway 分发逻辑
│   │   ├── platform/               # 18+ 平台适配器（核心资产）
│   │   ├── event_bus.py            # 事件总线
│   │   ├── agent/                  # 原生 LLM/Agent（可关闭）
│   │   ├── provider/               # 模型提供商（可关闭）
│   │   └── ...
│   ├── dashboard/
│   │   └── routes/
│   │       └── gateway.py            # ⭐ 新增：网关 REST + WS 端点
│   └── api/                        # 插件 API 暴露
├── tests/gateway/                  # ⭐ 新增：网关单元测试
├── docs/
│   ├── gateway-human-guide.md      # 给人看的中文文档
│   └── gateway-agent-spec.md     # 给 Agent 看的协议规范
├── dashboard/                      # Vue3 管理面板（可选）
└── main.py                         # 入口
```

---

## 文档

| 文档 | 面向读者 | 内容 |
|------|---------|------|
| [`docs/gateway-human-guide.md`](docs/gateway-human-guide.md) | AstraBot 维护者 / 运维 | 中文配置指南、UMO 格式、常见问题 |
| [`docs/gateway-agent-spec.md`](docs/gateway-agent-spec.md) | 外部 Agent 开发者（Hermes / Dify / Coze） | 协议规范、请求示例、Hermes 集成代码、错误处理、最小 Checklist |

---

## 回发示例

外部 Agent 处理完消息后，通过统一 HTTP API 回发：

```bash
POST http://astrbot-host:6185/api/v1/im/message
Authorization: Bearer abk_xxx
Content-Type: application/json

{
  "umo": "telegram:FriendMessage:telegram!123456789",
  "message": [
    {"type": "plain", "text": "Hello from Hermes"}
  ]
}
```

`umo` 格式：`platform_name:MessageType:session_id`

---

## 技术栈

- **Python 3.10+** — 主运行时
- **Quart** — 异步 Web 框架（Dashboard + OpenAPI）
- **aiohttp** — 网关 HTTP 客户端
- **asyncio** — 事件总线与消息队列
- **SQLite** — 会话、配置持久化

---

## 协议与许可

本项目基于 [AGPL-v3](LICENSE) 开源。如果你对本分支进行了修改并将其用于提供具有商业盈利性质的网络服务，你必须开源所做的修改。

---

## 致谢

本分支基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 开发。AstrBot 是一个优秀的开源 Agent 聊天机器人平台，由全世界热心开源贡献者维护。

- 特别感谢 AstrBot 原作者及所有 Contributors ❤️
- 感谢 [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) — 伟大的猫猫框架

---

_私は、高性能ですから!_
