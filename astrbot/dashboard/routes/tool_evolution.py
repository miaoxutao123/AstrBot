import traceback

from quart import jsonify, request

from astrbot.core import logger
from astrbot.core.runtime.resilience_monitor import coding_resilience_monitor
from astrbot.core.tool_evolution.manager import tool_evolution_manager

from .route import Response, Route, RouteContext


class ToolEvolutionRoute(Route):
    def __init__(
        self,
        context: RouteContext,
    ) -> None:
        super().__init__(context)
        self.routes = [
            ("/tool_evolution/overview", ("GET", self.overview)),
            ("/tool_evolution/propose", ("POST", self.propose)),
            ("/tool_evolution/apply", ("POST", self.apply)),
            ("/tool_evolution/guardrails", ("GET", self.guardrails)),
            ("/tool_evolution/resilience", ("GET", self.resilience_snapshot)),
            ("/tool_evolution/resilience/reset", ("POST", self.resilience_reset)),
        ]
        self.register_routes()

    async def overview(self):
        try:
            tool_name = request.args.get("tool_name", "", type=str)
            window = request.args.get("window", 200, type=int)
            data = await tool_evolution_manager.get_overview(
                tool_name=tool_name or None,
                window=window,
            )
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to get overview: {e!s}").__dict__)

    async def propose(self):
        try:
            payload = await request.get_json(silent=True)
            payload = payload or {}
            tool_name = str(payload.get("tool_name", "")).strip()
            if not tool_name:
                return jsonify(Response().error("tool_name is required").__dict__)
            min_samples = int(payload.get("min_samples", 12))
            data = await tool_evolution_manager.propose_policy(
                tool_name=tool_name,
                min_samples=min_samples,
            )
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to propose policy: {e!s}").__dict__
            )

    async def apply(self):
        try:
            payload = await request.get_json(silent=True)
            payload = payload or {}
            tool_name = str(payload.get("tool_name", "")).strip()
            if not tool_name:
                return jsonify(Response().error("tool_name is required").__dict__)
            dry_run = bool(payload.get("dry_run", True))
            min_samples = int(payload.get("min_samples", 12))
            data = await tool_evolution_manager.apply_policy(
                tool_name=tool_name,
                dry_run=dry_run,
                min_samples=min_samples,
            )
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to apply policy: {e!s}").__dict__)

    async def guardrails(self):
        try:
            data = await tool_evolution_manager.get_guardrails()
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get guardrails: {e!s}").__dict__
            )

    async def resilience_snapshot(self):
        try:
            data = await coding_resilience_monitor.get_snapshot()
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to get resilience snapshot: {e!s}").__dict__
            )

    async def resilience_reset(self):
        try:
            data = await coding_resilience_monitor.reset()
            return jsonify(Response().ok(data=data).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(
                Response().error(f"Failed to reset resilience snapshot: {e!s}").__dict__
            )
