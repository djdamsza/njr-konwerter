import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tidal_auth


class TidalCredentialTests(unittest.TestCase):
    def test_bundled_file_is_used_when_home_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / "tidal-credentials.json"
            bundled.write_text(
                json.dumps({"client_id": "app-id", "client_secret": "app-secret"}),
                encoding="utf-8",
            )
            missing = Path(tmp) / "missing.json"
            with patch.dict(os.environ, {"TIDAL_CLIENT_ID": "", "TIDAL_CLIENT_SECRET": ""}, clear=False), patch.object(
                tidal_auth, "_credential_files", return_value=[missing, bundled]
            ):
                self.assertEqual(tidal_auth._load_credentials(), ("app-id", "app-secret"))

    def test_home_file_wins_over_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home.json"
            bundled = Path(tmp) / "bundled.json"
            home.write_text(json.dumps({"client_id": "home-id", "client_secret": "home-secret"}), encoding="utf-8")
            bundled.write_text(json.dumps({"client_id": "app-id", "client_secret": "app-secret"}), encoding="utf-8")
            with patch.dict(os.environ, {"TIDAL_CLIENT_ID": "", "TIDAL_CLIENT_SECRET": ""}, clear=False), patch.object(
                tidal_auth, "_credential_files", return_value=[home, bundled]
            ):
                self.assertEqual(tidal_auth._load_credentials(), ("home-id", "home-secret"))


if __name__ == "__main__":
    unittest.main()
