# Agent 自适配接入契约

Gateway 只负责传输、事件和命令；Agent 自己负责推理、记忆、工具、原生会话，以及独立的 Gateway Adapter/Sidecar。先读取 `/.well-known/astrbot-gateway`，仅跟随返回的注册和 bootstrap 链接，再读取 `agent_integration`；不要猜测 API 路径，也不要修改 Gateway。

长期运行的 Agent Runtime 优先使用 **HTTP mode**；只能通过命令调用的 Agent 使用 **command mode**。将 `astrbot.agent.invoke.v1` 映射到原生 AgentFlow，并返回 `astrbot.agent.result.v1`，保留 canonical structured segments。稳定映射 Gateway session key 与原生会话，返回 `external_session_id`，让下一条消息继续同一会话。

主动消息使用 bootstrap 提供的 commands link。注册得到的唯一 `GATEWAY_API_KEY` 应共同用于 bootstrap、事件、命令和心跳。运行：

```bash
astrbot-gateway-agent doctor --config agent-gateway.yaml
```

`packages/agent-bridge/examples/` 中的示例是通用协议模板，不是生产 Agent 接入实现。
