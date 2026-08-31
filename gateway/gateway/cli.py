"""Standalone AstrBot-Gateway command-line interface."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from gateway.config import ConfigError, check_config, load_config


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Gateway CLI.

    Args:
        argv: Optional arguments excluding the executable name.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="astrbot-gateway")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "check", "adapters"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument(
            "-c",
            "--config",
            type=Path,
            default=Path("gateway.yaml"),
        )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "check":
            result = check_config(config)
            print(
                "configuration valid; "
                f"adapter_types={','.join(result.adapter_types) or 'none'}; "
                f"instances={','.join(result.configured_instances) or 'none'}"
            )
            return 0
        if args.command == "adapters":
            result = check_config(config)
            configured = {
                adapter.type for adapter in config.adapters if adapter.enabled
            }
            for adapter_type in result.adapter_types:
                status = "configured" if adapter_type in configured else "available"
                print(f"{adapter_type}\t{status}")
            for adapter_type, error in sorted(result.discovery_failures.items()):
                print(f"{adapter_type}\tfailed: {error}")
            return 0
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError(
                'run requires: pip install "astrbot-gateway[api]"'
            ) from exc
        from gateway.host import build_host

        host = build_host(config)
        logging.basicConfig(level=logging.INFO)
        uvicorn.run(
            host.app,
            host=config.server.host,
            port=config.server.port,
        )
        return 0
    except (ConfigError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
