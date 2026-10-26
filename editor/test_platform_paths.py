import os
import unittest
from pathlib import Path
from unittest.mock import patch

import platform_paths


class PlatformPathTests(unittest.TestCase):
    def test_windows_folders(self):
        env = {"APPDATA": r"C:\Users\dj\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\dj\AppData\Local"}
        with patch.object(platform_paths, "is_windows", return_value=True), patch.object(
            platform_paths.platform, "system", return_value="Windows"
        ), patch.dict(os.environ, env, clear=False):
            support = str(platform_paths.app_support_dir()).replace("\\", "/")
            serato = str(platform_paths.serato_sqlite_dir()).replace("\\", "/")
            vdj = str(platform_paths.vdj_root()).replace("\\", "/")
            self.assertTrue(support.endswith("AppData/Roaming/NJR Konwerter"))
            self.assertTrue(serato.endswith("AppData/Local/Serato/Library"))
            self.assertTrue(vdj.endswith("Documents/VirtualDJ"))
            self.assertEqual(platform_paths.plain_quit("Zamknij Serato (Cmd+Q)."), "Zamknij Serato.")
            self.assertEqual(
                platform_paths.plain_quit("Skopiuj do ~/Music/_Serato_/Subcrates/"),
                "Skopiuj do Music\\_Serato_\\Subcrates/",
            )

    def test_mac_folders_stay(self):
        home = Path("/Users/test")
        with patch.object(platform_paths, "is_windows", return_value=False), patch.object(
            platform_paths.platform, "system", return_value="Darwin"
        ), patch.object(Path, "home", return_value=home):
            self.assertEqual(
                platform_paths.vdj_root(),
                home / "Library" / "Application Support" / "VirtualDJ",
            )
            self.assertEqual(
                platform_paths.serato_sqlite_dir(),
                home / "Library" / "Application Support" / "Serato" / "Library",
            )
            self.assertEqual(platform_paths.plain_quit("Zamknij (Cmd+Q)."), "Zamknij (Cmd+Q).")

    def test_patriot_windows_uses_drive_letter(self):
        from engine_stems import _patriot_missing, resolve_patriot_dir

        with patch.object(platform_paths, "is_windows", return_value=True), patch.object(
            platform_paths, "windows_volume_root", return_value=Path("E:/")
        ):
            found = resolve_patriot_dir(Path("/Volumes/Patriot/Engine Library"))
            self.assertEqual(found, Path("E:/Engine Library"))
        with patch.object(platform_paths, "is_windows", return_value=True), patch.object(
            platform_paths, "windows_volume_root", return_value=None
        ):
            target, message = _patriot_missing(None)
            self.assertIsNone(target)
            self.assertNotIn("Volumes", message)

    def test_shortcuts_only_for_frozen_windows(self):
        with patch.object(platform_paths, "is_windows", return_value=False), patch(
            "subprocess.run"
        ) as run:
            platform_paths.ensure_windows_shortcuts()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
