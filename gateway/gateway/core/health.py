"""Shared adapter lifecycle state contract."""

from enum import Enum


class AdapterState(str, Enum):
    """Lifecycle and health state of one configured adapter instance."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"
