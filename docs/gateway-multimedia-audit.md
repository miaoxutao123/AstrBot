# AstraBot 统一网关 — 多媒体支持完备性评估报告

> 评估范围：Message Components 定义、平台适配器收发、网关序列化、回发通道、测试覆盖、文档一致性。  
> 对应分支：`feat/unified-gateway`  
> 评估日期：2026-06-10

---

## 1. 评估结论

**多媒体支持不完备。** 存在 3 个核心缺陷，1 个文档不一致，1 个测试缺失。

---

## 2. 逐层评估详情

### 2.1 Message Components 定义（✅ 完备）

`astrbot/core/message/components.py` 定义了 4 个多媒体组件，能力完整：

| 组件 | 来源 | 转换方法 | 文件服务注册 |
|------|------|---------|-------------|
| `Image` | `fromURL`, `fromFileSystem`, `fromBase64`, `fromBytes`, `fromIO` | `convert_to_file_path()`, `convert_to_base64()` | `register_to_file_service()` |
| `Record` | `fromURL`, `fromFileSystem`, `fromBase64` | `convert_to_file_path()`, `convert_to_base64()` | `register_to_file_service()` |
| `Video` | `fromURL`, `fromFileSystem` | `convert_to_file_path()` | `register_to_file_service()` |
| `File` | `name` + `file_` / `url` | `get_file()` | `register_to_file_service()` |

每个组件都有 `to_dict()` / `toDict()` 方法，可用于平台适配器发送时的序列化。

**结论**：组件层定义完整，无需改动。

---

### 2.2 平台适配器收发能力（✅ 基本完备，差异属平台限制）

- **`aiocqhttp`** (`_from_segment_to_dict`): 对 `Image`/`Record` 转 `base64://`，对 `File` 处理 `file:///` URI，对 `Video` 用 `to_dict()`。发送逻辑正确。
- **`telegram` / `discord` / `lark` / `kook` / `slack` / `wecom` 等**：均通过 `send_by_session()` 发送 `MessageChain`，内部遍历 chain 并调用各组件的 `to_dict()` 或 `convert_to_file_path()`。
- **接收端**：各适配器的 `convert_message()` 将平台原始消息解析为 `AstrBotMessage`，其中 `message` 字段为 `list[BaseMessageComponent]`。例如 `aiocqhttp` 会把 OneBot JSON 中的 `image` 段转为 `Image(file=url)`，`record` 段转为 `Record` 等。

**注意**：不同 IM 平台本身对多媒体类型支持不同（如 Discord 不支持 `Record` 语音段，某些平台不支持 `Video`），这是平台限制，非 AstraBot 缺陷。

**结论**：适配器层收发逻辑正确，无需改动。

---

### 2.3 网关序列化器 — 上行（IM → 外部 Agent）❌ 严重缺陷

**文件**：`astrbot/core/gateway/serializer.py`

当前实现：
```python
def component_to_dict(comp: BaseMessageComponent) -> dict:
    return {
        "type": comp.type.name if hasattr(comp.type, "name") else str(comp.type),
        "data": getattr(comp, "__dict__", {}),
    }
```

**缺陷清单**：

| # | 缺陷 | 影响 | 示例 |
|---|------|------|------|
| 1 | **不会自动注册到 `file_token_service`** | 外部 Agent 收到的是本地路径 `file:///C:/Users/...`，无法访问 | `Image(file="file:///C:/tmp/1.jpg")` → `{"data": {"file": "file:///C:/tmp/1.jpg"}}` |
| 2 | **Base64 直接暴露** | 如果组件是 `base64://...`，原始 base64 字符串直接塞进 JSON，导致 payload 巨大（一张 1MB 图片的 base64 约 1.33MB） | `Image(file="base64://...")` → JSON 中携带 1.33MB 字符串 |
| 3 | **字段名不一致** | `File` 组件的 `__dict__` 中字段是 `file_`（带下划线），而 `Image` 是 `file`（不带下划线），外部 Agent 解析时需要特殊处理 | `File` 的 `data` 中会有 `file_` 和 `name`，没有 `file` |
| 4 | **包含无用/内部字段** | `__dict__` 可能包含 `path`（AstraBot 内部临时路径）、`_type`（Pydantic 内部字段）等 | 外部 Agent 看到 `path`、`url`、`file` 等多个冗余字段，不知道用哪个 |

**理想行为**：
- 对 `Image` / `Record` / `Video` / `File` 组件，优先调用 `await comp.register_to_file_service()` 生成可下载 URL（`http://astrbot-host/api/file/{token}`）。
- 如果 `register_to_file_service()` 失败（如未配置 `callback_api_base`），回退到 `comp.url`（如果已是 http URL）或 `comp.file`（如果已是 http URL）。
- 统一输出字段：`file` 为可下载 URL，`name` 为文件名（仅 File），`text` 为原始文本（仅 Record）。

**结论**：序列化器必须重写，否则外部 Agent 无法处理多媒体上行消息。

---

### 2.4 回发通道 — 下行（外部 Agent → IM）❌ 重大缺陷

**文件**：`astrbot/core/platform/sources/webchat/message_parts_helper.py`

当前 `build_webchat_message_parts` 对多媒体的逻辑：
```python
attachment_id = part.get("attachment_id")
if not attachment_id:
    if strict:
        raise ValueError(f"{part_type} part missing attachment_id")
    continue
attachment = await get_attachment_by_id(str(attachment_id))
```

**缺陷清单**：

| # | 缺陷 | 影响 |
|---|------|------|
| 1 | **不支持 `url` 直接传入** | 外部 Agent 无法直接发送 `{"type": "image", "url": "https://..."}`。文档声称支持，但代码不支持。 |
| 2 | **必须先用 Dashboard 上传文件获取 `attachment_id`** | 外部 Agent 需要额外实现文件上传流程，增加了接入复杂度。 |
| 3 | **WebSocket `handle_send_message` 传入 `get_attachment_by_id=None`** | 如果外部 Agent 通过 WS 回发并带 `attachment_id`，会抛 `TypeError: 'NoneType' object is not callable`。 |

**文档不一致**：`docs/gateway-agent-spec.md` §6.2 表格声称：
```markdown
| `image` | `url` or `file` | `{"type":"image","url":"https://..."}` |
| `file` | `url` or `file` | `{"type":"file","url":"https://..."}` |
| `record` | `url` or `file` | `{"type":"record","url":"https://..."}` |
```
但代码实际只认 `attachment_id` 或 `path`。

**理想行为**：
- 在 `build_webchat_message_parts` 中增加对 `url` 字段的支持：
  - 如果 `url` 存在且以 `http` 开头，调用 `Image.fromURL(url)` / `Record.fromURL(url)` / `Video.fromURL(url)` / `File(name, url=url)`。
  - 如果 `file` 存在且是本地路径，调用 `fromFileSystem(file)`。
- 修复 `GatewayWebSocketHandler.handle_send_message` 传入 `get_attachment_by_id=None` 的问题，应使用 `self.db.get_attachment_by_id`（需要把 DB 引用传入）。

**结论**：回发通道必须支持 `url` 字段，否则外部 Agent 几乎无法发送多媒体。

---

### 2.5 测试覆盖（❌ 缺失）

`tests/gateway/` 现有测试：
- `test_envelope.py`：只测 `Plain` 和 `At`，没有 `Image`, `Record`, `Video`, `File`。
- `test_dispatcher.py`, `test_longpoll.py`, `test_webhook.py`：没有多媒体相关测试。

**缺失测试**：
1. `Image` 序列化后是否包含 `file_token_service` URL（或 http URL）。
2. `Record` 序列化后是否包含 `text` 和 `file`。
3. `File` 序列化后字段名是否统一（`file` 而非 `file_`）。
4. 多媒体回发：`url` 方式、`attachment_id` 方式、`path` 方式。
5. WebSocket `send_message` 含多媒体的端到端测试。

**结论**：需要补充多媒体测试。

---

### 2.6 文档一致性（⚠️ 有误导）

| 文档 | 问题 |
|------|------|
| `docs/gateway-agent-spec.md` §6.2 | 错误声称回发支持 `url` 或 `file`，实际只支持 `attachment_id` / `path` |
| `docs/gateway-human-guide.md` | 未提及多媒体限制，未说明外部 Agent 必须通过 Dashboard 上传文件才能发送图片 |

**结论**：需要修正文档，或同步修复代码以支持 `url`。

---

## 3. 修复优先级与建议

| 优先级 | 修复项 | 文件 | 改动量 | 说明 |
|--------|--------|------|--------|------|
| **P0** | 网关序列化器支持多媒体 URL 生成 | `serializer.py` | 中 | 对 `Image`/`Record`/`Video`/`File` 调用 `register_to_file_service()` 或回退到 `url` |
| **P0** | 回发通道支持 `url` 字段 | `message_parts_helper.py` | 中 | 在 `build_webchat_message_parts` 中增加 `url` 分支 |
| **P0** | 修复 WS `handle_send_message` 的 `None` DB 引用 | `websocket.py` | 小 | 传入 `self.db.get_attachment_by_id` 或改用 `url` 方式绕过 |
| **P1** | 统一多媒体组件序列化字段 | `serializer.py` | 小 | 隐藏 `file_`、`path` 等内部字段，统一输出 `file` + `name` |
| **P1** | 补充多媒体测试 | `tests/gateway/` | 中 | 新增 `test_multimedia.py` |
| **P1** | 修正文档 | `docs/gateway-agent-spec.md` | 小 | 更新 §6.2 表格，或等代码修复后同步更新 |

---

## 4. 最小修复后的多媒体数据流

### 上行（IM → 外部 Agent）

```
IM 平台发送图片
  → PlatformAdapter.convert_message() 解析为 Image(file="https://...") 或 Image(file="file:///...")
  → MessageSerializer.to_envelope()
       如果是 http URL → 直接使用
       如果是本地路径 → 调用 register_to_file_service() → http://astrbot/api/file/{token}
  → MessageEnvelope.message.chain[0] = {"type": "Image", "data": {"file": "http://..."}}
  → Webhook / LongPoll / WebSocket 推送给外部 Agent
  → 外部 Agent 通过 HTTP GET 下载文件
```

### 下行（外部 Agent → IM）

```
外部 Agent 发送图片
  → POST /api/v1/im/message
       {"umo": "...", "message": [{"type": "image", "url": "https://example.com/img.png"}]}
  → build_message_chain_from_payload()
       识别 url 字段 → Image.fromURL(url) → Image(file="https://...")
  → platform_inst.send_by_session(session, MessageChain)
       调用 Image.to_dict() / convert_to_file_path() 转为平台特定格式
  → IM 平台发送图片
```

---

## 5. 总结

| 维度 | 状态 | 说明 |
|------|------|------|
| 组件定义 | ✅ 完备 | `Image`/`Record`/`Video`/`File` 定义完整 |
| 平台适配器收发 | ✅ 基本完备 | 发送/接收逻辑正确，差异属平台限制 |
| 网关序列化（上行） | ❌ 有严重缺陷 | 不会生成可下载 URL，直接暴露本地路径/base64 |
| 回发通道（下行） | ❌ 有重大缺陷 | 不支持 `url` 直接传入，文档与代码不一致 |
| WebSocket 回发 | ❌ 有崩溃风险 | `handle_send_message` 传入 `None` DB 引用 |
| 测试覆盖 | ❌ 缺失 | 无多媒体序列化/回发测试 |
| 文档一致性 | ⚠️ 有误导 | `gateway-agent-spec.md` §6.2 错误声称支持 `url` |

**建议**：按 P0 优先级修复序列化器和回发通道，补充测试，修正文档。修复后多媒体支持可达到**完备**状态。
