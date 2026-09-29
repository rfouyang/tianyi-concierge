import struct
import unittest

from component.map_building.service import ConciergeMapBuilder
from util.slam_helper.map_renderer import MapRenderer


def explore_map(width=2, height=2):
    """Create the smallest valid Slamware explore-map response."""
    header = struct.pack("<ffIIf", 0.0, 0.0, width, height, 1.0)
    reserved = b"\0" * 12
    cells = bytes([0]) * (width * height)
    return header + reserved + struct.pack("<I", len(cells)) + cells


class MapRendererTests(unittest.TestCase):
    def test_incomplete_home_dock_does_not_break_preview(self):
        image = MapRenderer.render_explore_map(
            {
                "map_data": explore_map(),
                "robot_pose": {"x": 0, "y": 0},
                "home_dock": {"id": "dock-without-pose"},
            }
        )

        self.assertEqual(image.shape, (2, 2, 3))

    def test_pose_requires_x_and_y(self):
        self.assertTrue(MapRenderer.is_xy_pose({"x": 1, "y": 2}))
        self.assertFalse(MapRenderer.is_xy_pose({"id": "dock"}))


class MapBuildingRecoveryTests(unittest.TestCase):
    def test_stop_active_mapping_pauses_without_clearing(self):
        class Mapping:
            stopped = False
            waited_for = None

            @classmethod
            def is_enabled(cls):
                return True

            @classmethod
            def stop(cls, **kwargs):
                cls.stopped = True

            @classmethod
            def wait_enabled(cls, enabled, **kwargs):
                cls.waited_for = enabled

        class Slam:
            mapping = Mapping

        ConciergeMapBuilder(Slam()).stop_active_mapping()

        self.assertTrue(Mapping.stopped)
        self.assertFalse(Mapping.waited_for)


if __name__ == "__main__":
    unittest.main()
