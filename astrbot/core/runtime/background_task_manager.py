from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_TRANSIENT_ERROR_HINTS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "too many requests",
    "rate limit",
    "429",
    "502",
    "503",
    "504",
    "network",
    "retry later",
)


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 30.0


class BackgroundTaskManager:
    """Persistent runtime manager for long-running background tasks.

    This manager keeps task states in memory and persists snapshots to
    `data/runtime/background_tasks.json`.
    """

    def __init__(self) -> None:
        self.storage_dir = Path(get_astrbot_data_path()) / "runtime"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.storage_dir / "background_tasks.json"

        self._lock = asyncio.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._runtime_tasks: dict[str, asyncio.Task] = {}
        self._load()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _is_transient_error(self, error: str) -> bool:
        text = error.lower().strip()
        return any(hint in text for hint in _TRANSIENT_ERROR_HINTS)

    def _load(self) -> None:
        if not self.storage_file.exists():
            return
        try:
            data = json.loads(self.storage_file.read_text(encoding="utf-8"))
            tasks = data.get("tasks") if isinstance(data, dict) else None
            if isinstance(tasks, list):
                for task in tasks:
                    if isinstance(task, dict) and task.get("task_id"):
                        self._tasks[str(task["task_id"])] = task
        except Exception as exc:
            logger.warning("Failed to load background task store: %s", exc)

    def _serialize(self) -> None:
        try:
            tasks = sorted(
                self._tasks.values(),
                key=lambda item: item.get("created_at", ""),
                reverse=True,
            )
            # Keep a bounded history
            tasks = tasks[:1500]
            payload = {"tasks": tasks}
            self.storage_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist background task store: %s", exc)

    async def create_task(
        self,
        *,
        tool_name: str,
        session_id: str,
        tool_args: dict[str, Any],
        note: str = "",
        retry_policy: RetryPolicy | None = None,
    ) -> str:
        policy = retry_policy or RetryPolicy()
        task_id = uuid.uuid4().hex
        async with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "tool_name": tool_name,
                "session_id": session_id,
                "status": "queued",
                "attempt": 0,
                "max_attempts": max(1, int(policy.max_attempts)),
                "base_backoff_seconds": float(policy.base_backoff_seconds),
                "max_backoff_seconds": float(policy.max_backoff_seconds),
                "created_at": self._now(),
                "started_at": None,
                "finished_at": None,
                "last_error": None,
                "result": "",
                "note": note,
                "tool_args": tool_args,
                "events": [
                    {
                        "ts": self._now(),
                        "event": "created",
                        "message": "Task created and queued.",
                    }
                ],
            }
            self._serialize()
        return task_id

    async def attach_runtime_task(
        self, task_id: str, runtime_task: asyncio.Task
    ) -> None:
        async with self._lock:
            self._runtime_tasks[task_id] = runtime_task

    async def _append_event(self, task_id: str, event: str, message: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        task.setdefault("events", []).append(
            {"ts": self._now(), "event": event, "message": message}
        )
        # Keep recent events compact
        task["events"] = task["events"][-60:]

    async def _set_status(
        self,
        task_id: str,
        *,
        status: str,
        attempt: int | None = None,
        started: bool = False,
        finished: bool = False,
        last_error: str | None = None,
        result: str | None = None,
    ) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = status
            if attempt is not None:
                task["attempt"] = int(attempt)
            if started and not task.get("started_at"):
                task["started_at"] = self._now()
            if finished:
                task["finished_at"] = self._now()
            if last_error is not None:
                task["last_error"] = last_error
            if result is not None:
                task["result"] = result
            self._serialize()

    async def list_tasks(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        if session_id:
            tasks = [task for task in tasks if task.get("session_id") == session_id]
        tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return tasks[: max(1, min(limit, 300))]

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    async def cancel_task(self, task_id: str) -> bool:
        async with self._lock:
            runtime = self._runtime_tasks.get(task_id)
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.get("status") in {"succeeded", "failed", "cancelled"}:
                return False
            task["status"] = "cancelled"
            task["finished_at"] = self._now()
            self._serialize()
        if runtime and not runtime.done():
            runtime.cancel()
        await self._append_event(task_id, "cancelled", "Task cancelled by user.")
        async with self._lock:
            self._serialize()
        return True

    async def run_with_retry(
        self,
        *,
        task_id: str,
        attempt_runner,
        transient_detector=None,
    ) -> dict[str, Any]:
        """Run a background task with retry/self-healing.

        attempt_runner signature:
            async def attempt_runner(attempt_no: int) -> str

        Returns final task snapshot.
        """
        transient_detector = transient_detector or self._is_transient_error

        task_snapshot = await self.get_task(task_id)
        if not task_snapshot:
            raise ValueError(f"background task not found: {task_id}")

        max_attempts = int(task_snapshot.get("max_attempts") or 3)
        base_backoff = float(task_snapshot.get("base_backoff_seconds") or 2.0)
        max_backoff = float(task_snapshot.get("max_backoff_seconds") or 30.0)

        await self._set_status(task_id, status="running", started=True)
        await self._append_event(task_id, "running", "Task execution started.")

        last_error = ""
        for attempt in range(1, max_attempts + 1):
            await self._set_status(task_id, status="running", attempt=attempt)
            try:
                result = await attempt_runner(attempt)
                await self._set_status(
                    task_id,
                    status="succeeded",
                    attempt=attempt,
                    finished=True,
                    last_error="",
                    result=result,
                )
                await self._append_event(
                    task_id,
                    "succeeded",
                    f"Task succeeded on attempt {attempt}.",
                )
                break
            except asyncio.CancelledError:
                await self._set_status(task_id, status="cancelled", finished=True)
                await self._append_event(
                    task_id,
                    "cancelled",
                    "Task cancelled during execution.",
                )
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                is_transient = transient_detector(last_error)
                await self._set_status(
                    task_id,
                    status="retrying"
                    if is_transient and attempt < max_attempts
                    else "failed",
                    attempt=attempt,
                    last_error=last_error,
                    finished=not (is_transient and attempt < max_attempts),
                )
                await self._append_event(
                    task_id,
                    "retrying" if is_transient and attempt < max_attempts else "failed",
                    (
                        f"Attempt {attempt} failed with transient error: {last_error}"
                        if is_transient and attempt < max_attempts
                        else f"Attempt {attempt} failed: {last_error}"
                    ),
                )

                if not is_transient or attempt >= max_attempts:
                    break

                backoff = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
                await asyncio.sleep(backoff)

        snapshot = await self.get_task(task_id)
        if not snapshot:
            raise ValueError(f"background task missing after run: {task_id}")

        async with self._lock:
            runtime = self._runtime_tasks.get(task_id)
            if runtime and runtime.done():
                self._runtime_tasks.pop(task_id, None)

        if snapshot.get("status") != "succeeded" and last_error:
            logger.warning(
                "Background task %s failed after %s attempts: %s",
                task_id,
                snapshot.get("attempt"),
                last_error,
            )
        return snapshot


background_task_manager = BackgroundTaskManager()

__all__ = [
    "RetryPolicy",
    "BackgroundTaskManager",
    "background_task_manager",
]
