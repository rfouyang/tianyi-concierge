from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StcmIdentity:
    """Stable identity data extracted from one Slamware STCM document."""

    sha256: str
    canonical_sha256: str
    width: int
    height: int
    origin_x: float
    origin_y: float
    resolution_x: float
    resolution_y: float


def _read_pairs(data: bytes, offset: int, count: int) -> tuple[dict[str, str], int]:
    values = {}
    for _ in range(count):
        if offset + 2 > len(data):
            raise ValueError("STCM metadata is truncated")
        key_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        key_end = offset + key_size
        if key_end + 2 > len(data):
            raise ValueError("STCM metadata key is truncated")
        key = data[offset:key_end].decode("utf-8")
        offset = key_end

        value_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        value_end = offset + value_size
        if value_end > len(data):
            raise ValueError("STCM metadata value is truncated")
        values[key] = data[offset:value_end].decode("utf-8")
        offset = value_end
    return values, offset


def _trim_unknown_border(
    cells: bytes,
    width: int,
    height: int,
    origin_x: float,
    origin_y: float,
    resolution_x: float,
    resolution_y: float,
) -> tuple[bytes, int, int, float, float]:
    rows = [cells[index * width : (index + 1) * width] for index in range(height)]
    occupied_rows = [index for index, row in enumerate(rows) if any(row)]
    occupied_columns = [
        column
        for column in range(width)
        if any(rows[row][column] for row in range(height))
    ]
    if not occupied_rows or not occupied_columns:
        return b"", 0, 0, origin_x, origin_y

    top = occupied_rows[0]
    bottom = occupied_rows[-1] + 1
    left = occupied_columns[0]
    right = occupied_columns[-1] + 1
    trimmed = b"".join(row[left:right] for row in rows[top:bottom])
    return (
        trimmed,
        right - left,
        bottom - top,
        origin_x + left * resolution_x,
        origin_y + top * resolution_y,
    )


def inspect_stcm(data: bytes) -> StcmIdentity:
    """Create an identity resilient to Slamware trimming unknown map borders."""
    if len(data) < 24 or data[:4] != b"STCM":
        raise ValueError("File is not a supported STCM map")

    first_layer_size = struct.unpack_from("<I", data, 18)[0]
    first_layer_end = 22 + first_layer_size
    if first_layer_end > len(data):
        raise ValueError("STCM first layer is truncated")

    pair_count = struct.unpack_from("<H", data, 22)[0]
    metadata, grid_offset = _read_pairs(data, 24, pair_count)
    required = (
        "dimension_width",
        "dimension_height",
        "origin_x",
        "origin_y",
        "resolution_x",
        "resolution_y",
    )
    missing = [key for key in required if key not in metadata]
    if missing:
        raise ValueError(f"STCM grid metadata is missing: {', '.join(missing)}")

    width = int(metadata["dimension_width"])
    height = int(metadata["dimension_height"])
    origin_x = float(metadata["origin_x"])
    origin_y = float(metadata["origin_y"])
    resolution_x = float(metadata["resolution_x"])
    resolution_y = float(metadata["resolution_y"])
    if width <= 0 or height <= 0:
        raise ValueError("STCM grid dimensions must be positive")
    if resolution_x <= 0 or resolution_y <= 0:
        raise ValueError("STCM grid resolution must be positive")

    grid_size = width * height
    grid_end = grid_offset + grid_size
    if grid_end > first_layer_end:
        raise ValueError("STCM grid data is truncated")

    cells, canonical_width, canonical_height, canonical_x, canonical_y = (
        _trim_unknown_border(
            data[grid_offset:grid_end],
            width,
            height,
            origin_x,
            origin_y,
            resolution_x,
            resolution_y,
        )
    )
    canonical = hashlib.sha256()
    canonical.update(
        struct.pack(
            "<IIdddd",
            canonical_width,
            canonical_height,
            round(canonical_x, 5),
            round(canonical_y, 5),
            round(resolution_x, 8),
            round(resolution_y, 8),
        )
    )
    canonical.update(cells)
    canonical.update(data[first_layer_end:])
    return StcmIdentity(
        sha256=hashlib.sha256(data).hexdigest(),
        canonical_sha256=canonical.hexdigest(),
        width=width,
        height=height,
        origin_x=origin_x,
        origin_y=origin_y,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
    )


class MapIdentityRegistry:
    """Atomic local mapping from Slamware map UUIDs to operator-facing names."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def read(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return {"version": self.VERSION, "maps": {}}
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("version") != self.VERSION:
                raise ValueError("Unsupported map identity registry version")
            if not isinstance(document.get("maps"), dict):
                raise ValueError("Map identity registry must contain a maps object")
            return document

    def get(self, map_id: str | None) -> dict | None:
        if not map_id:
            return None
        return self.read()["maps"].get(str(map_id))

    def set(self, map_id: str, value: dict) -> None:
        if not map_id:
            raise ValueError("Cannot register a map without its Slamware map ID")
        with self._lock:
            document = self.read()
            document["maps"][str(map_id)] = value
            content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, self.path)
