# Agent 自助接入 Gateway

管理员在控制平面的“Agent”页面创建一次性注册授权后，只需安全地向 Harness 提供 `GATEWAY_URL` 与 `GATEWAY_ENROLLMENT_TOKEN`。不要把 token 写入提示词、日志或长期配置。

Harness 先读取 `/.well-known/astrbot-gateway`，从响应中取得注册地址并提交 enrollment token。注册响应会返回独立的 Agent API key；将它仅保存到 `GATEWAY_API_KEY` 环境变量。随后使用该 key 获取 `/v1/agent/bootstrap`，其中包含已授权的清单、WebSocket、命令、心跳地址和默认订阅。

普通 IM 消息的默认订阅固定为 `family=im`、`event_type=im.message`。安装并配置 Universal Agent Bridge 后运行：

```bash
astrbot-gateway-agent doctor --config agent-gateway.yaml
astrbot-gateway-agent run --config agent-gateway.yaml
```

Bridge 是通用协议桥；Harness 需要提供符合 `astrbot.agent.invoke.v1` / `astrbot.agent.result.v1` 的本地命令或 HTTP wrapper。
