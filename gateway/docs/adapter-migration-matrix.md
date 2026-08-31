# Adapter Migration Matrix

This matrix tracks implementation maturity only. A simulated integration pass is
not a real platform smoke pass.

| Adapter | Phase | Status | Automated coverage | Real smoke |
| --- | ---: | --- | --- | --- |
| OneBot v11 | 3 | `INTEGRATION_PASS` | Unit, contract, loopback WebSocket, mocked action, API integration | `REAL_SMOKE_PENDING` |
| Telegram | 4 | `INTEGRATION_PASS` | Unit, contract, mocked SDK lifecycle, API integration | `REAL_SMOKE_PENDING` |
| Weixin | 5 | `NOT_STARTED` | None | Not run |
| Satori | 6 | `NOT_STARTED` | None | Not run |
| Discord | 8 | `NOT_STARTED` | None | Not run |
| Slack | 8 | `NOT_STARTED` | None | Not run |
| QQ Official | 8 | `NOT_STARTED` | None | Not run |
| Feishu | 8 | `NOT_STARTED` | None | Not run |
| DingTalk | 8 | `NOT_STARTED` | None | Not run |
| LINE | 8 | `NOT_STARTED` | None | Not run |
| WeCom | 8 | `NOT_STARTED` | None | Not run |

WebChat is intentionally not a transport migration target; the Gateway HTTP and
WebSocket APIs replace its coupling role for external agents.
