import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from util.tailwind_asset_helper import TailwindAssetHelper


class TailwindAssetHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        (root / "src").mkdir()
        self.output = root / "app.css"
        self.helper = TailwindAssetHelper(
            project_root=root,
            input_path=root / "src" / "input.css",
            output_path=self.output,
            source_directories=(root / "src",),
        )
        self.helper.input_path.write_text("@import 'tailwindcss';")

    def tearDown(self):
        self.temporary.cleanup()

    def make_stale(self):
        self.output.write_text("old")
        old = time.time() - 60
        os.utime(self.output, (old, old))

    def test_serves_previous_build_when_npm_is_missing(self):
        self.make_stale()
        with patch.object(TailwindAssetHelper, "find_npm", return_value=None):
            self.assertFalse(self.helper.ensure_built())
        self.assertEqual(self.output.read_text(), "old")

    def test_fails_clearly_when_there_is_no_build_at_all(self):
        with patch.object(TailwindAssetHelper, "find_npm", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "never been built"):
                self.helper.ensure_built()

    def test_finds_npm_under_nvm_when_not_on_path(self):
        nvm = Path(self.temporary.name) / "nvm"
        for version in ("v18.20.0", "v22.23.3"):
            npm = nvm / "versions" / "node" / version / "bin" / "npm"
            npm.parent.mkdir(parents=True)
            npm.write_text("")
        with (
            patch("shutil.which", return_value=None),
            patch.dict(os.environ, {"NVM_DIR": str(nvm)}),
        ):
            self.assertIn("v22.23.3", TailwindAssetHelper.find_npm())
