"""CLI for creating, validating, and running generic Bridge configurations."""

import argparse
import asyncio
import os
from pathlib import Path

from astrbot_gateway_sdk import AsyncGatewayClient

from .config import BridgeConfig
from .runtime import AgentBridge


TEMPLATE = """gateway:\n  url: {url}\n  api_key_env: GATEWAY_API_KEY\nevents:\n  family: im\n  event_type: im.message\nagent:\n  mode: command\n  command: [python, ./agent_gateway_wrapper.py]\nsessions:\n  backend: sqlite\n  path: ./agent-sessions.db\nruntime:\n  max_concurrency: 4\n  invoke_timeout: 900\n"""

async def _doctor(config: BridgeConfig) -> int:
    key = os.getenv(config.api_key_env)
    if not key: print(f"Authentication              FAIL ({config.api_key_env} is unset)"); return 1
    async with AsyncGatewayClient(config.gateway_url, api_key=key) as client:
        inventory = await client.discover()
    print("Gateway                     OK\nAuthentication              OK\nDiscovery                   OK")
    for item in inventory.adapters: print(f"{item.adapter_id:<28} {item.state.upper():<10} {item.effective_direction}")
    return 0

def main() -> None:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init"); init.add_argument("--gateway", required=True); init.add_argument("--config", default="agent-gateway.yaml")
    for name in ("doctor", "run", "discover"):
        command = sub.add_parser(name); command.add_argument("--config", default="agent-gateway.yaml")
    args = parser.parse_args()
    if args.action == "init": Path(args.config).write_text(TEMPLATE.format(url=args.gateway), encoding="utf-8"); return
    config = BridgeConfig.load(Path(args.config)); key = os.getenv(config.api_key_env, "")
    if args.action == "doctor": raise SystemExit(asyncio.run(_doctor(config)))
    if args.action == "discover": raise SystemExit(asyncio.run(_doctor(config)))
    bridge = AgentBridge(config, key)
    try: print("Agent Bridge ready."); asyncio.run(bridge.run())
    finally: asyncio.run(bridge.aclose())
