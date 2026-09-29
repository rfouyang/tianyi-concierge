from .concierge_task import ConciergeBodyAction, ConciergeStop, ConciergeTask
from .docking import DockingService
from .errors import ConciergeTaskCancelled
from .execution_checkpoint import ConciergeExecutionCheckpoint
from .execution_options import ConciergeExecutionOptions
from .navigation import NavigationService
from .speech import SpeechService

__all__ = [
    "BodyActionClient",
    "DockingService",
    "ConciergeExecutionCheckpoint",
    "ConciergeExecutionOptions",
    "ConciergeBodyAction",
    "ConciergeStop",
    "ConciergeTask",
    "ConciergeTaskCancelled",
    "NavigationService",
    "SpeechService",
]


def __getattr__(name: str):
    """Keep the public body-action import without eagerly importing ROS code."""
    if name == "BodyActionClient":
        from .body_action import BodyActionClient

        return BodyActionClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
