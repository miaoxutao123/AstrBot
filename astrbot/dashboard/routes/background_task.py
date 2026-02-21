import traceback

from quart import jsonify, request

from astrbot.core import logger
from astrbot.core.runtime.background_task_manager import background_task_manager

from .route import Response, Route, RouteContext


class BackgroundTaskRoute(Route):
    def __init__(
        self,
        context: RouteContext,
    ) -> None:
        super().__init__(context)
        self.routes = [
            ("/background_task/list", ("GET", self.list_tasks)),
            ("/background_task/get/<task_id>", ("GET", self.get_task)),
            ("/background_task/cancel/<task_id>", ("POST", self.cancel_task)),
        ]
        self.register_routes()

    async def list_tasks(self):
        try:
            limit = request.args.get("limit", 50, type=int)
            status = request.args.get("status", "", type=str)
            session_id = request.args.get("session_id", "", type=str)

            tasks = await background_task_manager.list_tasks(
                limit=limit,
                status=status or None,
                session_id=session_id or None,
            )
            return jsonify(Response().ok(data=tasks).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to list tasks: {e!s}").__dict__)

    async def get_task(self, task_id: str):
        try:
            task = await background_task_manager.get_task(task_id)
            if not task:
                return jsonify(Response().error("Task not found").__dict__)
            return jsonify(Response().ok(data=task).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to get task: {e!s}").__dict__)

    async def cancel_task(self, task_id: str):
        try:
            ok = await background_task_manager.cancel_task(task_id)
            if not ok:
                return jsonify(Response().error("Task cannot be cancelled").__dict__)
            task = await background_task_manager.get_task(task_id)
            return jsonify(Response().ok(data=task or {}).__dict__)
        except Exception as e:  # noqa: BLE001
            logger.error(traceback.format_exc())
            return jsonify(Response().error(f"Failed to cancel task: {e!s}").__dict__)
