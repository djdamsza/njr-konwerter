"""Bez konta NJR program nie oddaje narzędzi ani AI."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import app


class LoginGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["NJR_ACCOUNT_DIR"] = self.tmp.name
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("NJR_ACCOUNT_DIR", None)

    def test_tools_stay_closed_without_login(self):
        blocked = self.client.get("/api/playlists")
        self.assertEqual(blocked.status_code, 401)
        self.assertTrue(blocked.get_json().get("loginRequired"))
        self.assertEqual(self.client.get("/api/version").status_code, 200)
        self.assertEqual(self.client.get("/api/account/status").status_code, 200)

    def test_saved_account_opens_tools(self):
        (Path(self.tmp.name) / "account-session.json").write_text(
            json.dumps({"deviceToken": "test-device", "email": "dj@example.com"}),
            encoding="utf-8",
        )
        opened = self.client.get("/api/playlists")
        self.assertNotEqual(opened.status_code, 401)


if __name__ == "__main__":
    unittest.main()
