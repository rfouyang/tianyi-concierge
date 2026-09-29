from __future__ import annotations

STOP_STATUS_LABELS = {
    "preparing": "Preparing speech",
    "navigating": "Navigating",
    "body_preparing": "Preparing body pose",
    "performing_stop": "Action + speech",
    "stop_completed": "Completed",
}


def initial_stop_states(stop_count: int, start_stop_index: int = 0) -> list[str]:
    """Stops before a resume point are already complete."""
    return ["Completed"] * start_stop_index + ["Pending"] * (stop_count - start_stop_index)


def apply_progress_event(stop_states: list[str], event: dict) -> list[str]:
    """Update per-stop labels from one executor event (same rules as before)."""
    stop_index = event.get("stop_index")
    status = event.get("status")
    if stop_index and 1 <= stop_index <= len(stop_states) and status in STOP_STATUS_LABELS:
        stop_states[stop_index - 1] = STOP_STATUS_LABELS[status]
    if status == "completed":
        stop_states[:] = ["Completed"] * len(stop_states)
    elif status in {"failed", "cancelled"}:
        replacement = "Failed" if status == "failed" else "Cancelled"
        for index, value in enumerate(stop_states):
            if value != "Completed":
                stop_states[index] = replacement
                break
    return stop_states


def progress_rows(task: dict, stop_states: list[str]) -> list[dict]:
    return [
        {"order": index, "poi_name": stop["poi_name"], "status": stop_states[index - 1]}
        for index, stop in enumerate(task["stops"], start=1)
    ]
