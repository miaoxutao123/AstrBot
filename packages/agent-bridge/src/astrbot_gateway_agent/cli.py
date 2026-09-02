"""CLI for creating, validating, and running generic Bridge configurations."""

import argparse
import asyncio
import os
from pathlib import Path

from astrbot_gateway_sdk import AsyncGatewayClient

from .config import BridgeConfig
from .invokers import CommandInvoker, HttpInvoker
from .protocol import INVOKE_SCHEMA, parse_result
from .runtime import AgentBridge
from .sessions import SessionStore

TEMPLATE = """gateway:\n  url: {url}\n  api_key_env: GATEWAY_API_KEY\nevents:\n  family: im\n  event_type: im.message\nagent:\n  mode: command\n  command: [python, ./agent_gateway_wrapper.py]\nsessions:\n  backend: sqlite\n  path: ./agent-sessions.db\nruntime:\n  max_concurrency: 4\n  max_pending: 64\n  invoke_timeout: 900\n"""


async def _doctor(config: BridgeConfig) -> int:
    key = os.getenv(config.api_key_env)
    if not key:
        print(f"Authentication              FAIL ({config.api_key_env} is unset)")
        return 1
    async with AsyncGatewayClient(config.gateway_url, api_key=key) as client:
        inventory = await client.discover()
    event_ok = bool(inventory.access.get("events_read"))
    command_ok = bool(inventory.access.get("commands_send"))
    session = SessionStore(config.session_path)
    try:
        session.put("doctor", "doctor-session")
        invoker = (
            CommandInvoker(
                config.command,
                config.invoke_timeout,
                config.max_stdout_bytes,
                config.env_allowlist,
            )
            if config.mode == "command"
            else HttpInvoker(str(config.agent_url), config.invoke_timeout)
        )
        result = await invoker.invoke(
            {
                "schema": INVOKE_SCHEMA,
                "session": {"key": "doctor", "external_session_id": None},
                "input": {
                    "type": "im.message",
                    "text": "doctor",
                    "segments": [],
                    "event": {},
                },
                "context": {"gateway_url": config.gateway_url},
            }
        )
        parse_result(result)
    except Exception as exc:
        print(f"Agent invocation            FAIL ({exc})")
        return 1
    finally:
        session.close()
    print(
        "Gateway                     OK\nAuthentication              OK\nDiscovery                   OK"
    )
    print(f"Event subscription          {'OK' if event_ok else 'FAIL'}")
    print(f"Command permission          {'OK' if command_ok else 'FAIL'}")
    print("Agent invocation            OK\nSession store               OK")
    for item in inventory.adapters:
        print(
            f"{item.adapter_id:<28} {item.state.upper():<10} {item.effective_direction}"
        )
    return 0 if event_ok and command_ok else 1


async def _discover(config: BridgeConfig) -> int:
    """Print only the authenticated Gateway inventory; never invoke a Harness."""
    key = os.getenv(config.api_key_env)
    if not key:
        print(f"Authentication              FAIL ({config.api_key_env} is unset)")
        return 1
    async with AsyncGatewayClient(config.gateway_url, api_key=key) as client:
        inventory = await client.discover()
    print("Gateway discovery")
    for item in inventory.adapters:
        print(
            f"{item.adapter_id:<28} {item.state.upper():<10} {item.effective_direction}"
        )
    return 0


async def _run_bridge(config: BridgeConfig, key: str) -> None:
    bridge = AgentBridge(config, key)
    try:
        print("Agent Bridge ready.")
        await bridge.run()
    finally:
        await bridge.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--gateway", required=True)
    init.add_argument("--config", default="agent-gateway.yaml")
    for name in ("doctor", "run", "discover"):
        command = sub.add_parser(name)
        command.add_argument("--config", default="agent-gateway.yaml")
    args = parser.parse_args()
    if args.action == "init":
        Path(args.config).write_text(
            TEMPLATE.format(url=args.gateway), encoding="utf-8"
        )
        return
    config = BridgeConfig.load(Path(args.config))
    key = os.getenv(config.api_key_env, "")
    if args.action == "doctor":
        raise SystemExit(asyncio.run(_doctor(config)))
    if args.action == "discover":
        raise SystemExit(asyncio.run(_discover(config)))
    asyncio.run(_run_bridge(config, key))
