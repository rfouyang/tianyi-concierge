"""Build the local Tailwind and Preline bundle when sources change."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True, slots=True)
class TailwindAssetHelper:
    """Keep generated CSS current without a separate launch command."""

    project_root: Path
    input_path: Path
    output_path: Path
    source_directories: tuple[Path, ...]

    @classmethod
    def for_concierge(cls, *, project_root: Path) -> TailwindAssetHelper:
        ui_root = project_root / "app" / "ui_concierge"
        return cls(
            project_root=project_root,
            input_path=ui_root / "static" / "css" / "input.css",
            output_path=ui_root / "static" / "css" / "app.css",
            source_directories=(ui_root / "templates", ui_root / "static" / "js"),
        )

    def ensure_built(self) -> bool:
        """Rebuild changed CSS; keep serving the last build if that is impossible."""
        if not self.needs_build():
            return False
        npm = self.find_npm()
        if npm is None:
            return self._fallback("npm was not found on PATH or under ~/.nvm")
        env = {**os.environ, "PATH": f"{Path(npm).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
        try:
            tailwind_cli = self.project_root / "node_modules" / ".bin" / "tailwindcss"
            if not tailwind_cli.is_file():
                logger.info("Installing local frontend build dependencies")
                subprocess.run([npm, "install"], cwd=self.project_root, env=env, check=True)
            logger.info("Building updated Tailwind and Preline styles")
            subprocess.run([npm, "run", "build:css"], cwd=self.project_root, env=env, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            return self._fallback(f"the CSS build failed: {error}")
        if not self.output_path.is_file():
            raise RuntimeError(f"CSS build did not create {self.output_path}")
        return True

    @staticmethod
    def find_npm() -> str | None:
        """npm from PATH, else the newest nvm install (nvm is not always on PATH)."""
        found = shutil.which("npm")
        if found:
            return found
        nvm_dir = Path(os.getenv("NVM_DIR") or Path.home() / ".nvm")
        candidates = sorted(
            (nvm_dir / "versions" / "node").glob("*/bin/npm"),
            key=lambda path: tuple(
                int(part) if part.isdigit() else 0
                for part in path.parent.parent.name.lstrip("v").split(".")
            ),
        )
        return str(candidates[-1]) if candidates else None

    def _fallback(self, reason: str) -> bool:
        if not self.output_path.is_file():
            raise RuntimeError(f"The console CSS has never been built and {reason}.")
        logger.warning(f"Serving the previous console CSS build because {reason}.")
        return False

    def needs_build(self) -> bool:
        if not self.output_path.is_file():
            return True
        built_at = self.output_path.stat().st_mtime_ns
        return any(
            path.stat().st_mtime_ns > built_at for path in self._source_paths() if path.is_file()
        )

    def _source_paths(self) -> tuple[Path, ...]:
        package_sources = (
            self.project_root / "package.json",
            self.project_root / "package-lock.json",
        )
        directory_sources = tuple(
            path for directory in self.source_directories for path in directory.rglob("*")
        )
        return (self.input_path, *package_sources, *directory_sources)
