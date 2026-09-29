import math
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"


class MapRenderer:
    @staticmethod
    def draw_explore_map(map_info, output_path):
        image = MapRenderer.render_explore_map(map_info)
        height, width, _ = image.shape

        path = Path(output_path).expanduser()
        MapRenderer.save_png(path, image.tobytes(), width, height)
        logger.info(f"Saved explore map visualization: {path}")

        return path

    @staticmethod
    def render_explore_map(map_info):
        metadata, pixels = MapRenderer.draw_map(map_info["map_data"])

        start_range = map_info.get("start_range")
        if start_range is not None:
            MapRenderer.draw_start_range(pixels, metadata, start_range)

        start_point = map_info.get("start_point")
        if start_point is not None:
            MapRenderer.draw_start_point(pixels, metadata, start_point)

        start_pose = map_info.get("start_pose")
        if start_pose is not None:
            MapRenderer.draw_start_pose(pixels, metadata, start_pose)

        home_dock = map_info.get("home_dock")
        if home_dock is not None:
            pose = (
                home_dock.get("pose", home_dock)
                if isinstance(home_dock, dict)
                else None
            )
            if MapRenderer.is_xy_pose(pose):
                MapRenderer.draw_home_dock(pixels, metadata, pose)
            else:
                # A mapping run can outlive a browser session.  In that case
                # the UI may only know the dock ID, not its pose.  The map is
                # still useful, so omit the marker instead of crashing.
                logger.warning(
                    "Skipping home-dock marker: robot did not provide x/y pose"
                )

        for wall in map_info.get("walls", []):
            MapRenderer.draw_virtual_wall(pixels, metadata, wall)

        for poi in map_info.get("pois", []):
            MapRenderer.draw_poi(pixels, metadata, poi)

        robot_pose = map_info.get("robot_pose")
        if robot_pose is not None:
            MapRenderer.draw_robot_pose(pixels, metadata, robot_pose)

        return np.frombuffer(pixels, dtype=np.uint8).reshape(
            metadata["height"],
            metadata["width"],
            3,
        ).copy()

    @staticmethod
    def is_xy_pose(pose):
        """Return whether *pose* has the minimum data needed to draw a marker."""
        return isinstance(pose, dict) and "x" in pose and "y" in pose

    @staticmethod
    def set_pixel(pixels, width, height, x, y, color):
        if not 0 <= x < width or not 0 <= y < height:
            return

        index = (y * width + x) * 3
        pixels[index: index + 3] = bytes(color)

    @staticmethod
    def png_bytes(pixels, width, height):
        """Encode packed RGB pixels as a PNG without an imaging dependency."""
        raw_rows = bytearray()
        row_size = width * 3
        for y in range(height):
            row_start = y * row_size
            raw_rows.append(0)
            raw_rows.extend(pixels[row_start: row_start + row_size])

        def chunk(chunk_type, data):
            return (
                struct.pack(">I", len(data))
                + chunk_type
                + data
                + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
            )

        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        compressed = zlib.compress(bytes(raw_rows))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", compressed)
            + chunk(b"IEND", b"")
        )

    @staticmethod
    def save_png(path, pixels, width, height):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(MapRenderer.png_bytes(pixels, width, height))

    @staticmethod
    def render_base_map(map_data):
        """Return grid metadata and a marker-free PNG for browser overlays."""
        metadata, pixels = MapRenderer.draw_map(map_data)
        return metadata, MapRenderer.png_bytes(
            pixels, metadata["width"], metadata["height"]
        )

    @staticmethod
    def draw_circle(pixels, width, height, center_x, center_y, radius, color):
        radius_sq = radius * radius
        for y in range(center_y - radius, center_y + radius + 1):
            for x in range(center_x - radius, center_x + radius + 1):
                if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius_sq:
                    MapRenderer.set_pixel(pixels, width, height, x, y, color)

    @staticmethod
    def draw_circle_outline(
        pixels, width, height, center_x, center_y, radius, color, thickness=3
    ):
        outer_radius_sq = radius * radius
        inner_radius_sq = max(0, radius - thickness) ** 2

        for y in range(center_y - radius, center_y + radius + 1):
            for x in range(center_x - radius, center_x + radius + 1):
                distance_sq = (x - center_x) ** 2 + (y - center_y) ** 2
                if inner_radius_sq <= distance_sq <= outer_radius_sq:
                    MapRenderer.set_pixel(pixels, width, height, x, y, color)

    @staticmethod
    def draw_line(pixels, width, height, start_x, start_y, end_x, end_y, color):
        dx = abs(end_x - start_x)
        dy = -abs(end_y - start_y)
        step_x = 1 if start_x < end_x else -1
        step_y = 1 if start_y < end_y else -1
        error = dx + dy

        x = start_x
        y = start_y
        while True:
            MapRenderer.set_pixel(pixels, width, height, x, y, color)
            if x == end_x and y == end_y:
                break
            double_error = 2 * error
            if double_error >= dy:
                error += dy
                x += step_x
            if double_error <= dx:
                error += dx
                y += step_y

    @staticmethod
    def draw_map(map_data):
        if len(map_data) < 36:
            raise ValueError("Explore map response is too short")

        origin_x, origin_y, width, height, resolution = struct.unpack("<ffIIf", map_data[:20])
        data_size = struct.unpack("<I", map_data[32:36])[0]
        cells = map_data[36: 36 + data_size]
        expected_size = width * height
        if data_size != expected_size or len(cells) != expected_size:
            raise ValueError(
                f"Invalid explore map data size: expected {expected_size}, got {data_size}"
            )

        # SLAMTEC encodes occupancy as signed bytes from -128 to 127.
        # Adding 128 converts them to the grayscale representation used by
        # RoboStudio: dark is occupied, white is free, and mid-gray is unknown.
        cell_values = np.frombuffer(cells, dtype=np.int8).reshape(height, width)
        grayscale = (cell_values.astype(np.int16) + 128).astype(np.uint8)

        image = np.repeat(np.flipud(grayscale)[:, :, None], 3, axis=2)
        pixels = bytearray(image.tobytes())

        metadata = {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "width": width,
            "height": height,
            "resolution": resolution,
        }
        logger.debug(
            f"Explore map: origin=({origin_x}, {origin_y}), "
            f"size={width}x{height}, resolution={resolution}"
        )

        return metadata, pixels

    @staticmethod
    def draw_robot_pose(pixels, metadata, pose):
        x = int(round((pose["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(round((pose["y"] - metadata["origin_y"]) / metadata["resolution"]))
        y = metadata["height"] - 1 - source_y

        width = metadata["width"]
        height = metadata["height"]
        if not 0 <= x < width or not 0 <= y < height:
            logger.warning(f"Robot pose is outside explore map bounds: ({pose['x']}, {pose['y']})")
            return pixels

        MapRenderer.draw_circle(pixels, width, height, x, y, radius=5, color=(220, 30, 30))

        yaw = pose.get("yaw", 0)
        end_x = int(round(x + math.cos(yaw) * 16))
        end_y = int(round(y - math.sin(yaw) * 16))
        MapRenderer.draw_line(pixels, width, height, x, y, end_x, end_y, color=(220, 30, 30))

        return pixels

    @staticmethod
    def draw_start_point(pixels, metadata, point):
        x = int(round((point["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(round((point["y"] - metadata["origin_y"]) / metadata["resolution"]))
        y = metadata["height"] - 1 - source_y

        width = metadata["width"]
        height = metadata["height"]
        if not 0 <= x < width or not 0 <= y < height:
            logger.warning(
                f"Start point is outside explore map bounds: "
                f"({point['x']}, {point['y']})"
            )
            return pixels

        color = (20, 120, 255)
        MapRenderer.draw_line(pixels, width, height, x - 15, y, x + 15, y, color)
        MapRenderer.draw_line(pixels, width, height, x, y - 15, x, y + 15, color)
        MapRenderer.draw_circle(pixels, width, height, x, y, radius=9, color=color)
        MapRenderer.draw_circle(pixels, width, height, x, y, radius=5, color=(255, 255, 255))
        MapRenderer.draw_circle(pixels, width, height, x, y, radius=2, color=color)
        logger.info(f"Drew start point: ({point['x']}, {point['y']})")

        return pixels

    @staticmethod
    def draw_start_pose(pixels, metadata, pose):
        MapRenderer.draw_start_point(pixels, metadata, pose)

        x = int(round((pose["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(round((pose["y"] - metadata["origin_y"]) / metadata["resolution"]))
        y = metadata["height"] - 1 - source_y
        yaw = pose.get("yaw", 0)
        end_x = int(round(x + math.cos(yaw) * 20))
        end_y = int(round(y - math.sin(yaw) * 20))
        MapRenderer.draw_line(
            pixels,
            metadata["width"],
            metadata["height"],
            x,
            y,
            end_x,
            end_y,
            color=(20, 120, 255),
        )

        return pixels

    @staticmethod
    def draw_home_dock(pixels, metadata, pose):
        x = int(round((pose["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(round((pose["y"] - metadata["origin_y"]) / metadata["resolution"]))
        y = metadata["height"] - 1 - source_y
        width = metadata["width"]
        height = metadata["height"]

        if not 0 <= x < width or not 0 <= y < height:
            logger.warning(
                f"Home dock is outside explore map bounds: ({pose['x']}, {pose['y']})"
            )
            return pixels

        color = (30, 190, 80)
        radius = 11
        for offset in range(3):
            size = radius - offset
            MapRenderer.draw_line(
                pixels, width, height, x - size, y - size, x + size, y - size, color
            )
            MapRenderer.draw_line(
                pixels, width, height, x + size, y - size, x + size, y + size, color
            )
            MapRenderer.draw_line(
                pixels, width, height, x + size, y + size, x - size, y + size, color
            )
            MapRenderer.draw_line(
                pixels, width, height, x - size, y + size, x - size, y - size, color
            )

        yaw = pose.get("yaw", 0)
        end_x = int(round(x + math.cos(yaw) * 20))
        end_y = int(round(y - math.sin(yaw) * 20))
        MapRenderer.draw_line(pixels, width, height, x, y, end_x, end_y, color)

        return pixels

    @staticmethod
    def draw_poi(pixels, metadata, poi):
        pose = poi.get("pose", poi)
        x = int(round((pose["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(
            round((pose["y"] - metadata["origin_y"]) / metadata["resolution"])
        )
        y = metadata["height"] - 1 - source_y
        width = metadata["width"]
        height = metadata["height"]

        if not 0 <= x < width or not 0 <= y < height:
            name = poi.get("metadata", {}).get("display_name") or poi.get(
                "id", "POI"
            )
            logger.warning(f"POI is outside explore map bounds: {name}")
            return pixels

        color = (160, 60, 210)
        MapRenderer.draw_circle(pixels, width, height, x, y, radius=7, color=color)
        MapRenderer.draw_circle(
            pixels,
            width,
            height,
            x,
            y,
            radius=3,
            color=(255, 255, 255),
        )

        yaw = pose.get("yaw", 0)
        end_x = int(round(x + math.cos(yaw) * 14))
        end_y = int(round(y - math.sin(yaw) * 14))
        MapRenderer.draw_line(pixels, width, height, x, y, end_x, end_y, color)

        return pixels

    @staticmethod
    def draw_virtual_wall(pixels, metadata, wall):
        start = wall["start"]
        end = wall["end"]
        resolution = metadata["resolution"]
        height = metadata["height"]

        start_x = int(round((start["x"] - metadata["origin_x"]) / resolution))
        start_y = height - 1 - int(
            round((start["y"] - metadata["origin_y"]) / resolution)
        )
        end_x = int(round((end["x"] - metadata["origin_x"]) / resolution))
        end_y = height - 1 - int(
            round((end["y"] - metadata["origin_y"]) / resolution)
        )

        color = (255, 110, 20)
        for offset_x, offset_y in (
            (0, 0),
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
        ):
            MapRenderer.draw_line(
                pixels,
                metadata["width"],
                height,
                start_x + offset_x,
                start_y + offset_y,
                end_x + offset_x,
                end_y + offset_y,
                color,
            )

        MapRenderer.draw_circle(
            pixels,
            metadata["width"],
            height,
            start_x,
            start_y,
            radius=5,
            color=color,
        )
        MapRenderer.draw_circle(
            pixels,
            metadata["width"],
            height,
            end_x,
            end_y,
            radius=5,
            color=color,
        )

        return pixels

    @staticmethod
    def draw_start_range(pixels, metadata, start_range):
        center = start_range["center"]
        radius = start_range["radius"]
        x = int(round((center["x"] - metadata["origin_x"]) / metadata["resolution"]))
        source_y = int(
            round((center["y"] - metadata["origin_y"]) / metadata["resolution"])
        )
        y = metadata["height"] - 1 - source_y
        radius_pixels = int(round(radius / metadata["resolution"]))

        MapRenderer.draw_circle_outline(
            pixels,
            metadata["width"],
            metadata["height"],
            x,
            y,
            radius_pixels,
            color=(20, 120, 255),
        )
        logger.info(
            f"Drew relocalization range: center=({center['x']}, {center['y']}), "
            f"radius={radius} m"
        )

        return pixels


def demo_render_map():
    """Draw the current robot pose on the explore map."""

    if __package__:
        from .localization import LocalizationClient
        from .map_client import MapClient
    else:
        sys.path.insert(0, str(BASE_DIR))
        from util.slam_helper.localization import LocalizationClient
        from util.slam_helper.map_client import MapClient

    robot_pose = LocalizationClient().get_robot_pose()
    map_info = MapClient.explore_map(robot_pose)

    return MapRenderer.draw_explore_map(map_info, OUTPUT_DIR / "current.png")


def demo_start():
    """Draw the map coordinate origin as the starting point."""

    if __package__:
        from .map_client import MapClient
    else:
        sys.path.insert(0, str(BASE_DIR))
        from util.slam_helper.map_client import MapClient

    map_info = MapClient.explore_map(robot_pose=None)
    map_info["start_point"] = {"x": 0.0, "y": 0.0}

    return MapRenderer.draw_explore_map(map_info, OUTPUT_DIR / "start_point.png")


def demo_start_range():
    """Draw the configured relocalization center and search radius."""

    if __package__:
        from .map_client import MapClient
        from .motion import RELOCALIZATION_RADIUS, START_POINT
    else:
        sys.path.insert(0, str(BASE_DIR))
        from util.slam_helper.map_client import MapClient
        from util.slam_helper.motion import RELOCALIZATION_RADIUS, START_POINT

    map_info = MapClient.explore_map(robot_pose=None)
    map_info["start_point"] = START_POINT
    map_info["start_range"] = {
        "center": START_POINT,
        "radius": RELOCALIZATION_RADIUS,
    }

    return MapRenderer.draw_explore_map(map_info, OUTPUT_DIR / "start_range.png")


def main():
    output_path = demo_start_range()
    print(f"Map visualization saved to {output_path.resolve()}")


if __name__ == "__main__":
    main()
