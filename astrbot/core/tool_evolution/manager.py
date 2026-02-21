from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


@dataclass(slots=True)
class Guardrails:
    min_samples: int = 12
    min_train_samples: int = 6
    min_valid_samples: int = 4
    max_timeout_multiplier: float = 3.0
    max_blocked_args: int = 4
    min_confidence: float = 0.55
    max_train_valid_gap: float = 0.25
    rollback_eval_window: int = 20
    rollback_min_window: int = 10
    rollback_success_drop: float = 0.12


_PERSIST_MIN_INTERVAL_SECONDS = 1.0
_PERSIST_CALL_BATCH = 8
_MAX_ARGS_KEYS = 24
_MAX_ARGS_VALUE_CHARS = 240
_MAX_ARGS_DEPTH = 3


class ToolEvolutionManager:
    """Collect tool-call telemetry and support guarded self-iteration policies."""

    def __init__(self) -> None:
        self.storage_dir = Path(get_astrbot_data_path()) / "tool_evolution"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.storage_dir / "state.json"
        self.guardrails = Guardrails()

        self._lock = asyncio.Lock()
        self._calls: list[dict[str, Any]] = []
        self._policies: dict[str, dict[str, Any]] = {}
        self._policy_history: list[dict[str, Any]] = []
        self._auto_apply_markers: dict[str, int] = {}
        self._seq = 0
        self._dirty_call_count = 0
        self._last_persist_monotonic = time.monotonic()
        self._load()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            calls = payload.get("calls", [])
            policies = payload.get("policies", {})
            history = payload.get("policy_history", [])
            markers = payload.get("auto_apply_markers", {})
            if isinstance(calls, list):
                self._calls = [c for c in calls if isinstance(c, dict)]
            if isinstance(policies, dict):
                self._policies = {
                    str(k): v for k, v in policies.items() if isinstance(v, dict)
                }
            if isinstance(history, list):
                self._policy_history = [h for h in history if isinstance(h, dict)]
            if isinstance(markers, dict):
                self._auto_apply_markers = {
                    str(k): int(v)
                    for k, v in markers.items()
                    if str(k) and isinstance(v, int | float)
                }
            if self._calls:
                self._seq = max(int(c.get("seq", 0)) for c in self._calls)
        except Exception as exc:
            logger.warning("Failed to load tool evolution state: %s", exc)

    def _persist(self) -> None:
        try:
            payload = {
                "calls": self._calls[-3000:],
                "policies": self._policies,
                "policy_history": self._policy_history[-500:],
                "auto_apply_markers": self._auto_apply_markers,
            }
            self.state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist tool evolution state: %s", exc)

    def _persist_if_needed(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force:
            self._persist()
            self._dirty_call_count = 0
            self._last_persist_monotonic = now
            return

        self._dirty_call_count += 1
        if (
            self._dirty_call_count >= _PERSIST_CALL_BATCH
            or (now - self._last_persist_monotonic) >= _PERSIST_MIN_INTERVAL_SECONDS
        ):
            self._persist()
            self._dirty_call_count = 0
            self._last_persist_monotonic = now

    def _extract_unexpected_args(self, error: str) -> list[str]:
        if not error:
            return []
        result: list[str] = []

        for match in re.findall(
            r"unexpected keyword argument ['\"]([^'\"]+)['\"]", error
        ):
            result.append(match)

        for block in re.findall(r"忽略非期望参数[:：]?\s*\{([^}]*)\}", error):
            parts = [p.strip().strip("'\"") for p in block.split(",")]
            for part in parts:
                if part:
                    result.append(part)

        # de-dup while preserving first-seen order
        deduped: list[str] = []
        seen: set[str] = set()
        for item in result:
            key = str(item or "").strip()
            if not key or key in seen:
                continue
            deduped.append(key)
            seen.add(key)

        return deduped

    def _compact_arg_value(self, value: Any, depth: int = 0) -> Any:
        if depth >= _MAX_ARGS_DEPTH:
            return str(type(value).__name__)
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            if len(value) <= _MAX_ARGS_VALUE_CHARS:
                return value
            return value[:_MAX_ARGS_VALUE_CHARS] + "...(truncated)"
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= _MAX_ARGS_KEYS:
                    compact["__truncated__"] = f"more_keys={len(value) - _MAX_ARGS_KEYS}"
                    break
                compact[str(k)[:80]] = self._compact_arg_value(v, depth + 1)
            return compact
        if isinstance(value, list | tuple):
            items = list(value)
            compact_list = [
                self._compact_arg_value(v, depth + 1) for v in items[:_MAX_ARGS_KEYS]
            ]
            if len(items) > _MAX_ARGS_KEYS:
                compact_list.append(f"...(truncated {len(items) - _MAX_ARGS_KEYS} items)")
            return compact_list
        return str(value)[:_MAX_ARGS_VALUE_CHARS]

    def _compact_args(self, args: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(args, dict):
            return {}
        compact: dict[str, Any] = {}
        for idx, (k, v) in enumerate(args.items()):
            if idx >= _MAX_ARGS_KEYS:
                compact["__truncated__"] = f"more_keys={len(args) - _MAX_ARGS_KEYS}"
                break
            compact[str(k)[:80]] = self._compact_arg_value(v, depth=0)
        return compact

    def _split_train_valid(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        train = [row for row in rows if int(row.get("seq", 0)) % 2 == 1]
        valid = [row for row in rows if int(row.get("seq", 0)) % 2 == 0]
        return train, valid

    def _success_rate(self, rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        return sum(1 for row in rows if row.get("success")) / len(rows)

    def _timeout_error_rate(self, rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        timeout_hits = 0
        for row in rows:
            err = str(row.get("error") or "").lower()
            if "timeout" in err or "timed out" in err:
                timeout_hits += 1
        return timeout_hits / len(rows)

    def _guardrails_dict(self) -> dict[str, Any]:
        return asdict(self.guardrails)

    async def record_tool_call(
        self,
        *,
        tool_name: str,
        success: bool,
        args: dict[str, Any] | None,
        error: str | None,
        duration_s: float,
        policy_applied: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            self._seq += 1
            row = {
                "seq": self._seq,
                "ts": self._now(),
                "tool_name": tool_name,
                "success": bool(success),
                "duration_s": round(max(0.0, float(duration_s)), 4),
                "error": (error or "")[:1000],
                "args": self._compact_args(args),
                "unexpected_args": self._extract_unexpected_args(error or ""),
                "policy_applied": policy_applied or {},
            }
            self._calls.append(row)
            if len(self._calls) > 3000:
                self._calls = self._calls[-3000:]
            rolled_back = await self._maybe_auto_rollback(tool_name)
            self._persist_if_needed(force=rolled_back)

    async def _maybe_auto_rollback(self, tool_name: str) -> bool:
        policy = self._policies.get(tool_name)
        if not policy or not policy.get("active", False):
            return False

        applied_seq = int(policy.get("applied_seq", 0) or 0)
        if applied_seq <= 0:
            return False

        baseline = float(policy.get("baseline_success_rate", 0.0))
        post_calls = [
            row
            for row in self._calls
            if row.get("tool_name") == tool_name
            and int(row.get("seq", 0)) > applied_seq
        ]
        post_calls = post_calls[-self.guardrails.rollback_eval_window :]
        if len(post_calls) < self.guardrails.rollback_min_window:
            return False

        post_success = self._success_rate(post_calls)
        if post_success >= baseline - self.guardrails.rollback_success_drop:
            return False

        policy["active"] = False
        policy["rolled_back_at"] = self._now()
        policy["rollback_reason"] = (
            f"post success_rate {post_success:.3f} < baseline {baseline:.3f}"
        )
        self._policy_history.append(
            {
                "tool_name": tool_name,
                "action": "auto_rollback",
                "ts": self._now(),
                "detail": policy["rollback_reason"],
            }
        )
        return True

    async def get_overview(
        self, *, tool_name: str | None = None, window: int = 200
    ) -> dict[str, Any]:
        async with self._lock:
            rows = list(self._calls)
            policies = dict(self._policies)

        rows = rows[-max(20, min(window, 1000)) :]
        if tool_name:
            rows = [row for row in rows if row.get("tool_name") == tool_name]

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.get("tool_name", "unknown"), []).append(row)

        tools_summary = []
        for name, group_rows in grouped.items():
            success_rate = self._success_rate(group_rows)
            durations = [float(row.get("duration_s", 0.0)) for row in group_rows]
            timeout_rate = self._timeout_error_rate(group_rows)
            err_counter = Counter()
            for row in group_rows:
                err = str(row.get("error") or "").strip()
                if err:
                    err_counter[err[:120]] += 1
            tools_summary.append(
                {
                    "tool_name": name,
                    "samples": len(group_rows),
                    "success_rate": round(success_rate, 4),
                    "median_duration_s": round(statistics.median(durations), 4)
                    if durations
                    else 0.0,
                    "timeout_error_rate": round(timeout_rate, 4),
                    "top_errors": err_counter.most_common(3),
                    "active_policy": policies.get(name, {}).get("active", False),
                }
            )

        tools_summary.sort(key=lambda item: (item["success_rate"], -item["samples"]))

        return {
            "window": len(rows),
            "tools": tools_summary,
            "policy_count": sum(
                1 for policy in policies.values() if policy.get("active")
            ),
            "guardrails": self._guardrails_dict(),
        }

    def _build_candidate(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(rows) < self.guardrails.min_samples:
            return None

        train, valid = self._split_train_valid(rows)
        if (
            len(train) < self.guardrails.min_train_samples
            or len(valid) < self.guardrails.min_valid_samples
        ):
            return None

        timeout_rate_train = self._timeout_error_rate(train)
        timeout_rate_valid = self._timeout_error_rate(valid)

        mismatch_counter_train = Counter()
        mismatch_counter_valid = Counter()
        for row in train:
            mismatch_counter_train.update(row.get("unexpected_args") or [])
        for row in valid:
            mismatch_counter_valid.update(row.get("unexpected_args") or [])

        blocked_args = [
            arg
            for arg, count in mismatch_counter_train.most_common(
                self.guardrails.max_blocked_args
            )
            if count >= 2 and mismatch_counter_valid.get(arg, 0) >= 1
        ]

        actions: dict[str, Any] = {}
        reasons: list[str] = []

        if timeout_rate_train >= 0.18 and timeout_rate_valid >= 0.15:
            timeout_multiplier = min(
                self.guardrails.max_timeout_multiplier,
                round(1.0 + ((timeout_rate_train + timeout_rate_valid) / 2.0) * 2.2, 2),
            )
            if timeout_multiplier > 1.15:
                actions["timeout_multiplier"] = timeout_multiplier
                reasons.append(
                    f"timeout errors observed in train/valid ({timeout_rate_train:.2%}/{timeout_rate_valid:.2%})"
                )

        if blocked_args:
            actions["blocked_args"] = blocked_args[: self.guardrails.max_blocked_args]
            actions["drop_unknown_args"] = True
            reasons.append(
                "unexpected argument errors consistently appear in train/valid splits"
            )

        if not actions:
            return None

        train_success = self._success_rate(train)
        valid_success = self._success_rate(valid)
        gap = abs(train_success - valid_success)

        confidence = max(
            0.0,
            min(
                1.0,
                0.45
                + min(0.25, len(rows) / 400)
                + (0.15 if timeout_rate_valid >= 0.15 else 0.0)
                + (0.15 if bool(blocked_args) else 0.0)
                - min(0.2, gap),
            ),
        )

        candidate = {
            "actions": actions,
            "train_success_rate": round(train_success, 4),
            "valid_success_rate": round(valid_success, 4),
            "train_valid_gap": round(gap, 4),
            "train_samples": len(train),
            "valid_samples": len(valid),
            "confidence": round(confidence, 4),
            "reasons": reasons,
        }
        return candidate

    async def propose_policy(
        self, tool_name: str, *, min_samples: int | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            rows = [row for row in self._calls if row.get("tool_name") == tool_name]

        if min_samples is not None and len(rows) < max(
            self.guardrails.min_samples, int(min_samples)
        ):
            return {
                "tool_name": tool_name,
                "ok": False,
                "reason": f"insufficient samples: {len(rows)}",
                "required": max(self.guardrails.min_samples, int(min_samples)),
            }

        candidate = self._build_candidate(rows)
        if not candidate:
            return {
                "tool_name": tool_name,
                "ok": False,
                "reason": "no stable improvement signal after anti-overfit checks",
                "samples": len(rows),
            }

        return {
            "tool_name": tool_name,
            "ok": True,
            "samples": len(rows),
            "candidate": candidate,
            "guardrails": self._guardrails_dict(),
        }

    async def apply_policy(
        self,
        tool_name: str,
        *,
        dry_run: bool = True,
        min_samples: int | None = None,
    ) -> dict[str, Any]:
        proposal = await self.propose_policy(tool_name, min_samples=min_samples)
        if not proposal.get("ok"):
            return {
                "tool_name": tool_name,
                "ok": False,
                "dry_run": dry_run,
                "reason": proposal.get("reason", "proposal unavailable"),
                "proposal": proposal,
            }

        candidate = proposal["candidate"]
        confidence = float(candidate.get("confidence", 0.0))
        gap = float(candidate.get("train_valid_gap", 1.0))
        if confidence < self.guardrails.min_confidence:
            return {
                "tool_name": tool_name,
                "ok": False,
                "dry_run": dry_run,
                "reason": f"candidate confidence too low: {confidence:.3f}",
                "proposal": proposal,
            }
        if gap > self.guardrails.max_train_valid_gap:
            return {
                "tool_name": tool_name,
                "ok": False,
                "dry_run": dry_run,
                "reason": f"train/valid gap too high: {gap:.3f}",
                "proposal": proposal,
            }

        async with self._lock:
            current_policy = dict(self._policies.get(tool_name, {}))

        if (
            not dry_run
            and current_policy.get("active")
            and current_policy.get("actions") == candidate.get("actions")
        ):
            return {
                "tool_name": tool_name,
                "ok": True,
                "dry_run": False,
                "action": "noop",
                "reason": "equivalent policy already active",
                "policy": current_policy,
                "proposal": proposal,
            }

        if dry_run:
            return {
                "tool_name": tool_name,
                "ok": True,
                "dry_run": True,
                "action": "preview",
                "proposal": proposal,
            }

        async with self._lock:
            rows = [row for row in self._calls if row.get("tool_name") == tool_name]
            last_n = rows[-self.guardrails.rollback_eval_window :]
            baseline = self._success_rate(last_n) if last_n else 1.0

            old = self._policies.get(tool_name, {})
            policy = {
                "tool_name": tool_name,
                "active": True,
                "version": int(old.get("version", 0)) + 1,
                "applied_at": self._now(),
                "applied_seq": self._seq,
                "baseline_success_rate": round(baseline, 4),
                "actions": candidate.get("actions", {}),
                "confidence": confidence,
                "train_valid_gap": gap,
                "train_samples": candidate.get("train_samples", 0),
                "valid_samples": candidate.get("valid_samples", 0),
                "reasons": candidate.get("reasons", []),
            }
            self._policies[tool_name] = policy
            self._policy_history.append(
                {
                    "tool_name": tool_name,
                    "action": "apply",
                    "ts": self._now(),
                    "policy_version": policy["version"],
                    "actions": policy["actions"],
                    "confidence": confidence,
                }
            )
            self._persist_if_needed(force=True)

        return {
            "tool_name": tool_name,
            "ok": True,
            "dry_run": False,
            "action": "applied",
            "policy": self._policies.get(tool_name),
        }

    async def maybe_auto_apply(
        self,
        tool_name: str,
        *,
        min_samples: int = 12,
        dry_run: bool = True,
        every_n_calls: int = 10,
    ) -> dict[str, Any] | None:
        call_step = max(1, int(every_n_calls))
        min_required = max(self.guardrails.min_samples, int(min_samples))

        async with self._lock:
            sample_count = sum(
                1 for row in self._calls if row.get("tool_name") == tool_name
            )
            marker = self._auto_apply_markers.get(tool_name, 0)

        if sample_count < min_required:
            return None
        if sample_count % call_step != 0:
            return None
        if marker == sample_count:
            return None

        result = await self.apply_policy(
            tool_name=tool_name,
            dry_run=dry_run,
            min_samples=min_required,
        )

        async with self._lock:
            self._auto_apply_markers[tool_name] = sample_count
            self._persist_if_needed(force=True)

        if result.get("ok") and not result.get("dry_run", True):
            logger.info(
                "Tool evolution auto-apply triggered for %s: %s",
                tool_name,
                result.get("action", "applied"),
            )

        result["auto_apply"] = True
        result["samples"] = sample_count
        return result

    async def get_guardrails(self) -> dict[str, Any]:
        return self._guardrails_dict()

    async def adapt_tool_call(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        default_timeout: int,
        expected_params: list[str] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            policy = self._policies.get(tool_name)

        if not policy or not policy.get("active"):
            return {
                "args": dict(args),
                "tool_call_timeout": int(default_timeout),
                "applied": {},
            }

        actions = policy.get("actions", {}) if isinstance(policy, dict) else {}
        patched_args = dict(args)
        applied: dict[str, Any] = {}

        blocked_args = actions.get("blocked_args")
        if isinstance(blocked_args, list) and blocked_args:
            before = set(patched_args.keys())
            for arg in blocked_args[: self.guardrails.max_blocked_args]:
                patched_args.pop(str(arg), None)
            removed = sorted(before - set(patched_args.keys()))
            if removed:
                applied["blocked_args"] = removed

        if actions.get("drop_unknown_args") and expected_params is not None:
            expected = {str(name) for name in expected_params}
            before = set(patched_args.keys())
            patched_args = {k: v for k, v in patched_args.items() if k in expected}
            removed = sorted(before - set(patched_args.keys()))
            if removed:
                applied["drop_unknown_args"] = removed

        timeout_multiplier = actions.get("timeout_multiplier")
        timeout_value = int(default_timeout)
        if isinstance(timeout_multiplier, int | float):
            mul = max(
                1.0,
                min(self.guardrails.max_timeout_multiplier, float(timeout_multiplier)),
            )
            timeout_value = max(1, int(round(timeout_value * mul)))
            if timeout_value != int(default_timeout):
                applied["timeout_multiplier"] = mul

        return {
            "args": patched_args,
            "tool_call_timeout": timeout_value,
            "applied": applied,
        }


# singleton
tool_evolution_manager = ToolEvolutionManager()

__all__ = [
    "Guardrails",
    "ToolEvolutionManager",
    "tool_evolution_manager",
]
