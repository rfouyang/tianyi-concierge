"""Central paths and runtime settings for Tianyi Concierge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _port(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        port = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Resolve project paths and `.env` values from one explicit project root."""

    project_root: Path = PROJECT_ROOT
    console_host: str = "0.0.0.0"
    console_port: int = 8085
    mrt_host: str = "0.0.0.0"
    mrt_port: int = 8088
    mrt_api_key: str = field(default="", repr=False)
    ngrok_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls, project_root: Path = PROJECT_ROOT) -> AppSettings:
        load_dotenv(project_root / ".env")
        return cls(
            project_root=project_root,
            console_host=_env("CONCIERGE_HOST", "0.0.0.0") or "0.0.0.0",
            console_port=_port("CONCIERGE_PORT", 8085),
            mrt_host=_env("MRT_SERVICE_HOST", "0.0.0.0") or "0.0.0.0",
            mrt_port=_port("MRT_SERVICE_PORT", 8088),
            mrt_api_key=_env("MRT_API_KEY"),
            ngrok_api_key=_env("NGROK_API_KEY"),
        )

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def task_config_path(self) -> Path:
        return self.config_dir / "task.json"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def map_dir(self) -> Path:
        """Every STCM map: finished builds, robot snapshots, and loadable maps."""
        return self.data_dir / "maps"

    @property
    def map_registry_path(self) -> Path:
        return self.map_dir / "map_registry.json"

    @property
    def mrt_audio_dir(self) -> Path:
        return self.speech_dir

    @property
    def speech_dir(self) -> Path:
        """Speech synthesized once per unique text and replayed offline."""
        return self.data_dir / "tts"

    @property
    def mrt_enabled(self) -> bool:
        return bool(self.mrt_api_key)
