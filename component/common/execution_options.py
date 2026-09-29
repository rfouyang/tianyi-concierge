from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ConciergeExecutionOptions:
    """Defaults for one concierge task execution."""

    min_quality: int = 50
    home_timeout: int = 300
    charging_timeout: int = 60
    poll_interval: float = 1
    charging_retry_count: int = 3
    undock_distance: float = 0.3
    max_undock_distance: float = 0.6
    max_undock_pulses: int = 30
    undock_pulse_ms: int = 100
    move_timeout: int = 300
    acceptable_precision: float = 0.2
    fail_retry_count: int = 2
    speed_ratio: float = 0.5

    def with_overrides(self, **kwargs) -> "ConciergeExecutionOptions":
        allowed = {
            key: value
            for key, value in kwargs.items()
            if key in self.__dataclass_fields__
        }
        return replace(self, **allowed)
