from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


class CodingResilienceMonitor:
    """Track coding resilience events for LLM retries and recovery loops."""

    def __init__(self) -> None:
        self.storage_dir = Path(get_astrbot_data_path()) / "runtime"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_file = self.storage_dir / "coding_resilience.json"

        self._lock = asyncio.Lock()
        self._stats = {
            "llm_retry_count": 0,
            "step_retry_count": 0,
            "stream_fallback_count": 0,
            "recovered_count": 0,
            "failed_count": 0,
            "last_error": "",
            "last_error_at": "",
        }
        self._events: list[dict[str, Any]] = []
        self._load()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        if not self.storage_file.exists():
            return

        try:
            payload = json.loads(self.storage_file.read_text(encoding="utf-8"))
            stats = payload.get("stats") if isinstance(payload, dict) else None
            events = payload.get("events") if isinstance(payload, dict) else None

            if isinstance(stats, dict):
                for key in self._stats:
                    if key in {"last_error", "last_error_at"}:
                        self._stats[key] = str(stats.get(key) or "")
                    else:
                        self._stats[key] = int(stats.get(key, 0) or 0)

            if isinstance(events, list):
                self._events = [event for event in events if isinstance(event, dict)]
        except Exception as exc:
            logger.warning("Failed to load coding resilience stats: %s", exc)

    def _persist(self) -> None:
        try:
            payload = {
                "stats": self._stats,
                "events": self._events[-120:],
            }
            self.storage_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist coding resilience stats: %s", exc)

    async def record_event(
        self,
        *,
        event: str,
        detail: str = "",
        session_id: str = "",
    ) -> None:
        event = event.strip().lower()

        async with self._lock:
            if event == "llm_retry":
                self._stats["llm_retry_count"] += 1
            elif event == "step_retry":
                self._stats["step_retry_count"] += 1
            elif event == "stream_fallback":
                self._stats["stream_fallback_count"] += 1
            elif event == "recovered":
                self._stats["recovered_count"] += 1
            elif event == "failed":
                self._stats["failed_count"] += 1
                self._stats["last_error"] = detail[:500]
                self._stats["last_error_at"] = self._now()

            row = {
                "ts": self._now(),
                "event": event,
                "detail": detail[:500],
                "session_id": session_id,
            }
            self._events.append(row)
            self._events = self._events[-120:]
            self._persist()

    async def get_snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "stats": dict(self._stats),
                "recent_events": list(self._events[-40:]),
            }

    async def reset(self) -> dict[str, Any]:
        async with self._lock:
            self._stats = {
                "llm_retry_count": 0,
                "step_retry_count": 0,
                "stream_fallback_count": 0,
                "recovered_count": 0,
                "failed_count": 0,
                "last_error": "",
                "last_error_at": "",
            }
            self._events = []
            self._persist()
            return {
                "stats": dict(self._stats),
                "recent_events": [],
            }


coding_resilience_monitor = CodingResilienceMonitor()

__all__ = ["CodingResilienceMonitor", "coding_resilience_monitor"]
