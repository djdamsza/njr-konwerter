"""Konto NJR: hasło nie zostaje na dysku."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch
class _Response:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestNjrAccount(unittest.TestCase):
    def test_login_keeps_token_not_password(self):
        from njr_account import login, _session_path

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["NJR_ACCOUNT_DIR"] = tmp
            try:
                payload = {
                    "deviceToken": "a" * 64,
                    "email": "dj@example.com",
                    "tokens": 0,
                    "subscriptionActive": False,
                    "planName": "",
                    "subscriptionEndsAt": None,
                }
                with patch("njr_account.urlopen", return_value=_Response(payload)) as opened:
                    out = login("dj@example.com", "haslo-ktore-nie-zostaje")
                sent = opened.call_args[0][0]
                body = json.loads(sent.data.decode())
                self.assertEqual(body["password"], "haslo-ktore-nie-zostaje")
                self.assertTrue(out["signedIn"])
                saved = json.loads(_session_path().read_text(encoding="utf-8"))
                self.assertEqual(saved["deviceToken"], "a" * 64)
                self.assertNotIn("password", saved)
                self.assertNotIn("haslo-ktore-nie-zostaje", json.dumps(saved))
            finally:
                os.environ.pop("NJR_ACCOUNT_DIR", None)

    def test_google_poll_saves_token_without_password(self):
        from njr_account import google_poll, google_start, _session_path

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["NJR_ACCOUNT_DIR"] = tmp
            os.environ["NJR_ACCOUNT_SITE"] = "https://nowajakoscrozrywki.pl"
            try:
                started = google_start()
                self.assertIn("/api/konwerter/google/start?", started["url"])
                self.assertIn("state=" + started["state"], started["url"])
                payload = {
                    "deviceToken": "b" * 64,
                    "email": "google@example.com",
                    "tokens": 3,
                    "subscriptionActive": False,
                    "planName": "",
                    "subscriptionEndsAt": None,
                }
                with patch("njr_account.urlopen", return_value=_Response(payload)):
                    waiting = {"pending": True}
                    with patch("njr_account.urlopen", return_value=_Response(waiting)):
                        self.assertEqual(google_poll(started["state"]), {"pending": True})
                    out = google_poll(started["state"])
                self.assertTrue(out["signedIn"])
                self.assertEqual(out["email"], "google@example.com")
                saved = json.loads(_session_path().read_text(encoding="utf-8"))
                self.assertEqual(saved["deviceToken"], "b" * 64)
                self.assertNotIn("password", saved)
            finally:
                os.environ.pop("NJR_ACCOUNT_DIR", None)
                os.environ.pop("NJR_ACCOUNT_SITE", None)


if __name__ == "__main__":
    unittest.main()
