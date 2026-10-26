import unittest
from unittest import mock

import ai_flash


class TestModelFallback(unittest.TestCase):
    def setUp(self):
        ai_flash._blocked_until.clear()

    def test_quota_error_tries_the_next_model(self):
        self.assertTrue(ai_flash._should_try_next(429, "quota exceeded"))
        self.assertTrue(ai_flash._should_try_next(400, "RESOURCE_EXHAUSTED"))
        self.assertFalse(ai_flash._should_try_next(400, "invalid argument"))

    def test_daily_limit_blocks_longer_than_a_short_retry(self):
        self.assertGreater(ai_flash._cooldown_seconds("requests per day"), 3600)
        self.assertLess(ai_flash._cooldown_seconds("retry in 12s"), 60)

    def test_blocked_model_is_skipped(self):
        ai_flash._mark_blocked("gemini-3.6-flash", "requests per day")
        names = ai_flash._candidates()
        self.assertNotIn("gemini-3.6-flash", names)
        self.assertIn("gemini-3.5-flash-lite", names)
        self.assertIn("gemini-3.8-flash", names)

    def test_flash_preview_asks_the_site(self):
        with mock.patch("njr_account.ask_model", return_value={"model": "m", "sent": "cześć", "answer": "ok"}) as ask:
            out = ai_flash.flash_preview("cześć", max_chars=10)
        ask.assert_called_once_with("cześć", timeout=45)
        self.assertEqual(out["answer"], "ok")

    def test_missing_site_route_does_not_use_a_local_key(self):
        from njr_account import AccountError

        with mock.patch("njr_account.ask_model", side_effect=AccountError("Strona nie ma jeszcze połączenia z AI.", 503)):
            with mock.patch("ai_flash.gemini_api_key", return_value="local-key") as key:
                with self.assertRaises(ValueError) as caught:
                    ai_flash.flash_preview("cześć")
        key.assert_not_called()
        self.assertIn("nie ma jeszcze", str(caught.exception))

    def test_flash_preview_shows_the_site_error(self):
        from njr_account import AccountError

        with mock.patch("njr_account.ask_model", side_effect=AccountError("Zaloguj się, żeby użyć AI.", 401)):
            with self.assertRaises(ValueError) as caught:
                ai_flash.flash_preview("cześć")
        self.assertIn("Zaloguj", str(caught.exception))

    def test_chain_always_contains_every_model(self):
        with mock.patch.dict("os.environ", {"GEMINI_MODEL": "gemini-3.8-flash"}):
            order = ai_flash._model_order(("gemini-3.5-flash-lite",))
        self.assertEqual(order[0], "gemini-3.5-flash-lite")
        self.assertEqual(
            set(order),
            {"gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"},
        )


if __name__ == "__main__":
    unittest.main()
