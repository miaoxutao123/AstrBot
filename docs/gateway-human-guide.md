# AstraBot 统一网关（Unified Gateway）接入指南

> 适用于 AstraBot 维护者 / 开发者 / 自托管用户

## 1. 什么是统一网关？

AstraBot 原生是一个 All-in-One AI 助手，内置 LLM、Agent、知识库、插件等 heavy 模块。但有时候你只需要一个**纯粹的多 IM 接入层**：把 QQ、Telegram、微信、飞书、钉钉等 18+ 平台的消息统一接入，然后转发给你的外部 Agent 系统（如 Dify、Coze、Hermes、自研 Agent）处理。

**统一网关** 就是为此而生的。它保留了 AstraBot 强大的 IM 接入能力，但把 AI 处理逻辑完全外包。

```
IM 平台 → AstraBot PlatformAdapter → 统一网关 → 外部 Agent
                                    ↑
                              外部 Agent 回发 → AstraBot → 回复 IM
```

## 2. 三种上行通道

| 通道 | 方向 | 适用场景 | 网络要求 |
|------|------|---------|---------|
| **Webhook** | AstraBot → 外部 Agent（推送） | 云端 Agent、微服务 | Agent 需暴露 HTTP 接口 |
| **Long Polling** | 外部 Agent → AstraBot（拉取） | 本地 Agent、防火墙后 | Agent 无需暴露端口 |
| **WebSocket** | 双向全双工 | 高频交互、流式回复 | 双向可达 |

> 你可以同时启用三种通道，不同的 Agent 按需接入。

## 3. 快速配置

### 3.1 开启网关模式

在 `data/cmd_config.json` 中新增 `gateway` 配置段：

```json
{
  "gateway": {
    "enabled": true,
    "bypass_llm": true,
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
  }
}
```

配置说明：
- `enabled`: 总开关。设为 `true` 后，AstraBot 不再调用内置 LLM，所有消息走网关转发。
- **`bypass_llm`**（新增，安全选项）: 设为 `true` 时，Gateway 触发后直接强制转发，**无视任何前置 stage 的 `call_llm` 标记**。这能防止某个插件（如 LLM 意图识别）被提示词注入后，把消息绕过 Gateway 送入内置 LLM，导致敏感信息泄露或行为失控。推荐所有纯网关用户开启。
- `channels.webhook`: 主动推送模式。AstraBot 收到消息后，立刻 HTTP POST 到配置的 URL。
- `channels.longpoll`: 被动拉取模式。外部 Agent 定时 `GET /api/gateway/events` 拉取消息。
- `channels.websocket`: 全双工模式。外部 Agent 建立 WS 连接后，实时双向收发。

### 3.2 创建 API Key（用于 Long Poll / WebSocket / 回发）

在 Dashboard → 扩展 → API Key 管理 中创建新 Key：
- Scope 勾选 `im` + `gateway`
- 复制生成的 `abk_xxx` 密钥

### 3.3 关闭内置 LLM（可选但推荐）

```json
{
  "provider_settings": {
    "enable": false
  }
}
```

这样 AstraBot 不会加载任何 Provider，进一步降低资源占用。

## 4. 外部 Agent 回发消息

外部 Agent 处理完消息后，通过以下方式回发：

### 4.1 HTTP API（通用）

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

### 4.2 发送多媒体（图片 / 语音 / 视频 / 文件）

**方式一：直接 URL（推荐）**

外部 Agent 直接提供网络可访问的 URL，AstraBot 自动下载并转发到 IM 平台：

```json
{
  "umo": "telegram:FriendMessage:telegram!123456789",
  "message": [
    {"type": "plain", "text": "Check this out"},
    {"type": "image", "url": "https://example.com/chart.png"},
    {"type": "video", "url": "https://example.com/demo.mp4"},
    {"type": "file", "url": "https://example.com/report.pdf", "filename": "report.pdf"}
  ]
}
```

支持的多媒体类型：`image`、`record`（语音）、`video`、`file`。

> **注意**：WebSocket 回发通道（`op: send_message`）不支持 `attachment_id`（因为 WS 连接没有 Dashboard 数据库上下文），所以**务必使用 `url` 方式**。

**方式二：附件 ID（仅限 HTTP API）**

如果文件不便暴露公网 URL，可先通过 Dashboard 上传文件获取 `attachment_id`，然后在消息中引用：

```json
{
  "message": [
    {"type": "image", "attachment_id": "att_abc123"}
  ]
}
```

### 4.3 WebSocket（仅 WS 连接）

```json
{
  "op": "send_message",
  "data": {
    "umo": "telegram:FriendMessage:telegram!123456789",
    "message": [{"type": "plain", "text": "Hello from Hermes"}]
  }
}
```

## 5. 消息信封格式

AstraBot 向外部 Agent 推送的消息遵循统一信封（MessageEnvelope）：

### 5.1 纯文本消息

```json
{
  "event_id": "evt_2f4a8c...",
  "type": "im.message.receive",
  "version": "1.0",
  "timestamp": 1718340000,
  "platform": {
    "id": "tg_prod_bot",
    "name": "telegram",
    "type": "telegram"
  },
  "session": {
    "umo": "telegram:FriendMessage:telegram!123456789",
    "session_id": "123456789",
    "message_type": "FriendMessage",
    "group_id": ""
  },
  "sender": {
    "id": "123456789",
    "name": "Alice",
    "role": "member"
  },
  "message": {
    "text": "Hello bot",
    "chain": [
      {"type": "Plain", "data": {"text": "Hello bot"}}
    ]
  },
  "metadata": {
    "is_at": true,
    "is_wake": true,
    "is_private": true,
    "raw_message_id": "42"
  }
}
```

### 5.2 含多媒体的消息

当用户发送图片、语音、视频或文件时，`message.chain` 中会出现对应的多媒体段。AstraBot 会尝试将文件注册到内部下载服务，生成 `http://astrbot-host/api/file/{token}` 的可下载 URL，以便外部 Agent 直接下载：

```json
{
  "message": {
    "text": "[图片]",
    "chain": [
      {"type": "Image", "data": {"file": "http://astrbot-host/api/file/abc123..."}}
    ]
  }
}
```

如果 `callback_api_base` 未配置，序列化器会回退到原始 `url` 或 `file` 字段（如 `https://cdn.telegram.org/...`）。本地路径和 base64 不会被直接暴露。

**多媒体组件映射：**

| 用户发送 | chain 中的 type | data 字段 | 说明 |
|---------|----------------|----------|------|
| 图片 | `Image` | `file` | 可下载 URL |
| 语音 | `Record` | `file` | 可下载 URL；可能含 `text`（TTS 原文） |
| 视频 | `Video` | `file` | 可下载 URL |
| 文件 | `File` | `file`, `name` | 可下载 URL + 原始文件名 |

## 6. 常见问题

**Q: 可以同时启用网关和内置 LLM 吗？**
A: 可以，但逻辑上会冲突。建议要么走网关，要么走内置 LLM。网关启用时，ProcessStage 会优先转发给外部 Agent。

**Q: 插件（Star）还能用吗？**
A: 可以。如果插件 Handler 被激活（如关键词触发），事件会优先由插件处理，不会走网关转发。这让本地轻量过滤（如黑名单、关键词回复）仍然生效。

**Q: 支持群发吗？**
A: 支持。Agent 回发时批量调用 `POST /api/v1/im/batch`（v4.26+ 计划支持）。当前可以逐个调用 `/api/v1/im/message`。

**Q: 如何监控网关健康？**
A: 查看 AstraBot 日志中的 `Gateway dispatch` 相关信息。Webhook 失败会记录 `logger.warning`。

---

> 本指南对应分支 `feat/unified-gateway`。
