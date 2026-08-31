"""Top-level lifecycle ordering for the dependency-free Gateway Core."""

from .event_bus import MemoryEventBus
from .runtime import AdapterRuntime, AdapterRuntimeInfo


class GatewayLifecycle:
    """Start and stop the event bus and adapter runtime in safe order.

    Args:
        event_bus: Event bus that receives adapter events.
        runtime: Adapter runtime using the same event bus.
    """

    def __init__(
        self,
        event_bus: MemoryEventBus,
        runtime: AdapterRuntime,
    ) -> None:
        self._event_bus = event_bus
        self._runtime = runtime
        self._started = False

    async def start(self) -> list[AdapterRuntimeInfo]:
        """Start the bus before starting adapters.

        Returns:
            State of every adapter after startup.
        """
        if self._started:
            return self._runtime.list_info()
        await self._event_bus.start()
        self._started = True
        return await self._runtime.start_all()

    async def stop(self) -> list[AdapterRuntimeInfo]:
        """Stop adapters before draining and stopping the event bus.

        Returns:
            State of every adapter after shutdown.
        """
        if not self._started:
            return self._runtime.list_info()
        adapter_info = await self._runtime.stop_all()
        await self._event_bus.stop()
        self._started = False
        return adapter_info
