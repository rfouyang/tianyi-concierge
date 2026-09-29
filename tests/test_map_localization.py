import json
import struct
import tempfile
import unittest
from pathlib import Path

from component.map_building.service import ConciergeMapBuilder
from component.map_localization import ConciergeMapLocalizer, inspect_stcm


def make_stcm(
    width,
    height,
    cells,
    *,
    origin_x=0.0,
    origin_y=0.0,
    resolution=1.0,
    semantic_tail=b"semantic-data",
):
    metadata = {
        "dimension_width": str(width),
        "dimension_height": str(height),
        "origin_x": str(origin_x),
        "origin_y": str(origin_y),
        "resolution_x": str(resolution),
        "resolution_y": str(resolution),
    }
    pairs = bytearray()
    for key, value in metadata.items():
        encoded_key = key.encode()
        encoded_value = value.encode()
        pairs.extend(struct.pack("<H", len(encoded_key)))
        pairs.extend(encoded_key)
        pairs.extend(struct.pack("<H", len(encoded_value)))
        pairs.extend(encoded_value)
    layer = struct.pack("<H", len(metadata)) + pairs + bytes(cells) + b"\x00" * 4
    return b"STCM" + b"\x00" * 14 + struct.pack("<I", len(layer)) + layer + semantic_tail


def padded_map():
    return make_stcm(
        4,
        4,
        [
            0,
            0,
            0,
            0,
            0,
            10,
            20,
            0,
            0,
            30,
            40,
            0,
            0,
            0,
            0,
            0,
        ],
        origin_x=-1.0,
        origin_y=-1.0,
    )


def cropped_map():
    return make_stcm(2, 2, [10, 20, 30, 40])


class FakeMapClient:
    def __init__(self, current_map):
        self.current_map = current_map
        self.managed_by_cloud = False
        self.uploaded = []
        self.reloaded = 0
        self.synced = 0
        self.persisted = 0
        self.saved = []
        self.floors = [{"building": "default", "floor": "1f"}]
        self.calls = []

    def get_map_status(self):
        return {
            "map_load_status": "LOADED",
            "current_map_id": "map-123",
            "is_managed_by_cloud": self.managed_by_cloud,
            "is_homedock_binded": True,
        }

    def get_robot_current_floor(self):
        return {"map_id": "map-123", "building": "default", "floor": "1f"}

    def get_composite_map(self):
        return self.current_map

    def upload_map(self, path):
        self.calls.append("upload")
        self.uploaded.append(Path(path))
        self.stored = Path(path).read_bytes()

    def reload_map(self, **kwargs):
        self.calls.append("reload")
        self.reloaded += 1
        self.current_map = self.stored

    def get_floors(self):
        return self.floors

    def sync_map(self, **kwargs):
        self.synced += 1

    def persist_map(self, **kwargs):
        self.calls.append("persist")
        self.persisted += 1

    def save_map(self, **kwargs):
        self.calls.append("save")
        output_path = Path(kwargs["output_dir"]) / kwargs["filename"]
        output_path.write_bytes(self.current_map)
        self.saved.append(kwargs)
        return output_path


class FakeMapping:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def is_enabled(self):
        return self.enabled

    def stop(self, **kwargs):
        self.enabled = False

    def wait_enabled(self, enabled, **kwargs):
        return enabled


class FakeLocalization:
    def __init__(self):
        self.enabled = True
        self.quality = 80
        self.poses = []

    def is_enabled(self):
        return self.enabled

    def set_enabled(self, enabled):
        self.enabled = enabled
        return True

    def get_localization_quality(self):
        return self.quality

    def get_robot_pose(self):
        return {"x": 1.0, "y": 2.0, "yaw": 0.5}

    def set_robot_pose(self, pose):
        self.poses.append(pose)
        return pose


class FakeSystemStatus:
    def require_healthy(self):
        return {"healthy": True}


class FakeMotion:
    def __init__(self):
        self.relocalizations = []

    def get_current_action(self):
        return None

    def relocalization(self, **kwargs):
        self.relocalizations.append(kwargs)
        return {"state": {"status": 4, "result": 0}}


class FakeHomeDock:
    def __init__(self):
        self.on_dock = True
        self.relocalized = []

    def require_on_dock(self):
        if not self.on_dock:
            raise RuntimeError("Robot is not on the charging dock")
        return {"dockingStatus": "on_dock", "isCharging": True}

    bound = True

    def get_current_home_dock(self):
        return {"result": True, "data": {"id": "home_dock", "is_binded": self.bound}}

    def bind_home_dock(self, dock_id):
        self.bind_calls = getattr(self, "bind_calls", []) + [dock_id]
        self.bound = True

    def require_bound_home_dock(self):
        return {"id": "home_dock", "is_binded": True}

    drops_binding = False

    def relocalize_at_home_dock(self, dock_id):
        self.relocalized.append(dock_id)
        if self.drops_binding:
            self.bound = False

    def find_home_dock(self, dock_id):
        return {"id": dock_id, "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}


class FakePower:
    def require_charging(self, **kwargs):
        return kwargs["status"]


class FakeSlam:
    def __init__(self, current_map, mapping=False):
        self.map_client = FakeMapClient(current_map)
        self.mapping = FakeMapping(mapping)
        self.localization = FakeLocalization()
        self.system_status = FakeSystemStatus()
        self.motion = FakeMotion()
        self.home_dock = FakeHomeDock()
        self.power = FakePower()

    def require_action_success(self, action, label="SLAM action"):
        if action["state"]["result"] != 0:
            raise RuntimeError(f"{label} failed")
        return action


class MapIdentityTests(unittest.TestCase):
    def test_canonical_identity_ignores_trimmed_unknown_border(self):
        padded = inspect_stcm(padded_map())
        cropped = inspect_stcm(cropped_map())

        self.assertNotEqual(padded.sha256, cropped.sha256)
        self.assertEqual(padded.canonical_sha256, cropped.canonical_sha256)

    def test_semantic_data_remains_part_of_canonical_identity(self):
        first = inspect_stcm(cropped_map())
        changed = inspect_stcm(
            make_stcm(2, 2, [10, 20, 30, 40], semantic_tail=b"other-semantic-data")
        )

        self.assertNotEqual(first.canonical_sha256, changed.canonical_sha256)


class MapLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.map_dir = Path(self.temporary.name) / "maps"
        self.map_dir.mkdir()
        (self.map_dir / "office.stcm").write_bytes(padded_map())
        self.slam = FakeSlam(cropped_map())
        self.slam.localization.enabled = False
        self.service = ConciergeMapLocalizer(self.slam, map_dir=self.map_dir)

    def tearDown(self):
        self.temporary.cleanup()

    def test_maps_come_only_from_data_maps(self):
        self.assertEqual([item["name"] for item in self.service.list_maps()], ["office.stcm"])
        with self.assertRaises(ValueError):
            self.service.resolve_map("../output/debug.stcm")
        with self.assertRaises(FileNotFoundError):
            self.service.resolve_map("missing.stcm")

    def test_current_robot_map_matches_file_after_border_crop(self):
        identity = self.service.get_current_map_identity()

        self.assertTrue(identity["verified"])
        self.assertEqual(identity["display_name"], "office.stcm")
        self.assertEqual(identity["source"], "data/maps/office.stcm")
        self.assertEqual(identity["match"], "normalized")

    def test_load_is_locked_while_localization_runs(self):
        self.slam.localization.enabled = True

        with self.assertRaisesRegex(RuntimeError, "Stop localization"):
            self.service.load_map("office.stcm")

        self.assertEqual(self.slam.map_client.uploaded, [])

    def test_load_is_blocked_while_mapping_before_upload(self):
        self.slam.mapping.enabled = True

        with self.assertRaisesRegex(RuntimeError, "Stop map building"):
            self.service.load_map("office.stcm")

        self.assertEqual(self.slam.map_client.uploaded, [])

    def test_load_is_blocked_when_cloud_manages_the_map(self):
        self.slam.map_client.managed_by_cloud = True

        with self.assertRaisesRegex(RuntimeError, "managed by cloud"):
            self.service.load_map("office.stcm")

    def test_load_uploads_to_robot_storage_reloads_and_verifies(self):
        identity = self.service.load_map("office.stcm")

        self.assertEqual(self.slam.map_client.calls, ["upload", "reload"])
        self.assertEqual(self.slam.map_client.uploaded, [(self.map_dir / "office.stcm").resolve()])
        self.assertTrue(identity["verified"])
        registry = json.loads((self.map_dir / "map_registry.json").read_text())
        self.assertEqual(registry["maps"]["map-123"]["source"], "data/maps/office.stcm")

    def test_load_fails_when_reloaded_map_does_not_match(self):
        other = make_stcm(2, 2, [1, 2, 3, 4])
        self.slam.map_client.reload_map = lambda **kwargs: setattr(
            self.slam.map_client, "current_map", other
        )

        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.service.load_map("office.stcm")

    def test_sync_is_blocked_for_multiple_floors(self):
        self.slam.map_client.floors = [{"floor": "1f"}, {"floor": "2f"}]

        with self.assertRaisesRegex(RuntimeError, "exactly one floor"):
            self.service.sync_current_map()

        self.assertEqual(self.slam.map_client.synced, 0)

    def test_snapshot_is_saved_into_data_maps(self):
        path = self.service.save_snapshot("snapshot.stcm")

        self.assertEqual(path, self.map_dir / "snapshot.stcm")

    def test_localize_at_dock_uses_the_bound_dock(self):
        status = self.service.localize_at_dock()

        self.assertEqual(self.slam.home_dock.relocalized, ["home_dock"])
        self.assertTrue(self.slam.localization.enabled)
        self.assertEqual(status["quality"], 80)

    def test_localize_at_dock_restores_a_dropped_binding(self):
        self.slam.home_dock.drops_binding = True

        status = self.service.localize_at_dock()

        self.assertTrue(status["dock_rebound"])
        self.assertTrue(self.slam.home_dock.bound)
        self.assertEqual(self.slam.home_dock.bind_calls, ["home_dock"])

    def test_localize_at_dock_requires_the_dock(self):
        self.slam.home_dock.on_dock = False

        with self.assertRaisesRegex(RuntimeError, "not on the charging dock"):
            self.service.localize_at_dock()

        self.assertEqual(self.slam.home_dock.relocalized, [])

    def test_localize_at_pose_sets_pose_then_searches_locally_without_moving(self):
        self.service.localize_at_pose(3.0, 4.0, 1.5, search_half_size=1.0)

        self.assertEqual(self.slam.localization.poses, [{"x": 3.0, "y": 4.0, "yaw": 1.5}])
        search = self.slam.motion.relocalizations[0]
        self.assertEqual(search["area"], {"x": 2.0, "y": 3.0, "width": 2.0, "height": 2.0})
        self.assertEqual(search["recover_movement_type"], "NoMove")

    def test_localize_at_pose_rotates_only_when_allowed(self):
        self.service.localize_at_pose(0.0, 0.0, 0.0, allow_rotation=True)

        self.assertEqual(self.slam.motion.relocalizations[0]["recover_movement_type"], "RotateOnly")

    def test_localize_fails_when_quality_stays_low(self):
        self.slam.localization.quality = 30

        with self.assertRaisesRegex(RuntimeError, "needs at least 50"):
            self.service.localize_at_pose(0.0, 0.0, 0.0, quality_timeout=0, poll_interval=0)


class LocalizationStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.map_dir = Path(self.temporary.name)
        (self.map_dir / "office.stcm").write_bytes(padded_map())
        self.slam = FakeSlam(cropped_map())
        self.service = ConciergeMapLocalizer(self.slam, map_dir=self.map_dir)

    def tearDown(self):
        self.temporary.cleanup()

    def state(self, **overrides):
        values = {
            "enabled": self.slam.localization.enabled,
            "quality": self.slam.localization.quality,
            "map_status": self.slam.map_client.get_map_status(),
            "mapping": False,
        }
        values.update(overrides)
        return self.service.localization_state(**values)["state"]

    def test_starts_not_localized_even_with_good_quality(self):
        self.assertEqual(self.state(), "not_localized")
        with self.assertRaisesRegex(RuntimeError, "not localized"):
            self.service.require_localized()

    def test_dock_localization_marks_localized(self):
        self.service.localize_at_dock()

        self.assertEqual(self.state(), "localized")
        self.service.require_localized()

    def test_arrow_localization_marks_localized(self):
        self.service.localize_at_pose(1.0, 2.0, 0.0)

        self.assertEqual(self.state(), "localized")

    def test_low_quality_after_localizing_is_lost(self):
        self.service.localize_at_dock()

        self.assertEqual(self.state(quality=20), "lost")

    def test_running_localization_is_reported(self):
        self.assertEqual(self.state(localizing=True), "localizing")

    def test_stop_localization_clears_the_state(self):
        self.service.localize_at_dock()
        self.service.stop_localization()

        self.assertEqual(self.state(), "not_localized")

    def test_loading_a_map_clears_the_state(self):
        self.service.localize_at_dock()
        self.slam.localization.enabled = False
        self.service.load_map("office.stcm")
        self.slam.localization.enabled = True

        self.assertEqual(self.state(), "not_localized")

    def test_mapping_means_not_localized(self):
        self.service.localize_at_dock()

        self.assertEqual(self.state(mapping=True), "not_localized")

    def test_failed_localization_leaves_it_unconfirmed(self):
        self.slam.localization.quality = 30

        with self.assertRaises(RuntimeError):
            self.service.localize_at_pose(0.0, 0.0, 0.0, quality_timeout=0, poll_interval=0)

        self.assertNotEqual(self.state(quality=80), "localized")


class BindDockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.slam = FakeSlam(cropped_map())
        self.slam.home_dock.bound = False
        self.service = ConciergeMapLocalizer(self.slam, map_dir=Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_binds_the_maps_dock_and_confirms_it(self):
        dock = self.service.bind_home_dock()

        self.assertEqual(self.slam.home_dock.bind_calls, ["home_dock"])
        self.assertTrue(dock["is_binded"])

    def test_bind_requires_the_robot_on_the_dock(self):
        self.slam.home_dock.on_dock = False

        with self.assertRaisesRegex(RuntimeError, "not on the charging dock"):
            self.service.bind_home_dock()

        self.assertFalse(self.slam.home_dock.bound)

    def test_bind_is_single_floor_only(self):
        self.slam.map_client.floors = [{"floor": "1f"}, {"floor": "2f"}]

        with self.assertRaisesRegex(RuntimeError, "exactly one floor"):
            self.service.bind_home_dock()

    def test_already_bound_dock_is_left_alone(self):
        self.slam.home_dock.bound = True

        self.service.bind_home_dock()

        self.assertFalse(hasattr(self.slam.home_dock, "bind_calls"))


class MapBuildingFinishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.map_dir = Path(self.temporary.name) / "maps"
        self.map_dir.mkdir()
        self.slam = FakeSlam(cropped_map(), mapping=True)
        self.builder = ConciergeMapBuilder(self.slam, map_dir=self.map_dir)
        self.builder._session = {
            "active": True,
            "filename": "office3.stcm",
            "home_dock": {"id": "dock-1"},
            "start_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_finish_persists_on_robot_then_saves_to_data_maps(self):
        result = self.builder.finish()

        self.assertEqual(self.slam.map_client.calls, ["persist", "save"])
        self.assertEqual(Path(result["map_path"]), self.map_dir / "office3.stcm")
        self.assertFalse(self.builder.session["active"])

    def test_finish_refuses_to_save_with_multiple_floors(self):
        self.slam.map_client.floors = [{"floor": "1f"}, {"floor": "2f"}]

        with self.assertRaisesRegex(RuntimeError, "exactly one floor"):
            self.builder.finish()

        self.assertEqual(self.slam.map_client.persisted, 0)


if __name__ == "__main__":
    unittest.main()
