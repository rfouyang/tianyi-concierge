from __future__ import annotations

from ..task_execution.executor import ConciergeTaskExecutor


class ConciergeNavigator:
    """Manual navigation: visit one POI and speak, dock, undock, or stop.

    These share the executor's run lock, so manual moves never overlap a task.
    """

    def __init__(self, executor: ConciergeTaskExecutor) -> None:
        self.executor = executor

    def go_to_poi(self, poi_id: str, content: str | None = None) -> dict:
        """Navigate to a POI, speak, and stay there until moved or stopped."""
        return self.executor.debug_poi(poi_id, content=content)

    def go_home(self) -> dict:
        return self.executor.return_home()

    def undock(self) -> dict:
        """Dock-tag undock; not validated on this firmware (tours depart by navigation)."""
        return self.executor.undock()

    def stop(self) -> bool:
        """Cancel all motion without returning home; Tianyi stays where it is."""
        return self.executor.stop()
