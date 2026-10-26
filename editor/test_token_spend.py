"""Zużycie tokenu idzie na konto. Przy zerze kolejna praca AI nie startuje."""
from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import njr_account
import pimp_list


class _Site(BaseHTTPRequestHandler):
    balance = 3
    spends = []

    def log_message(self, fmt, *args):
        return

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode() or "{}")
        if self.path.endswith("/checkout"):
            self._json(200, {"url": "https://checkout.stripe.com/c/pay/test"})
            return
        if not self.path.endswith("/spend"):
            self._json(404, {"error": "missing"})
            return
        count = int(body.get("count") or 0)
        _Site.spends.append(count)
        if _Site.balance < count:
            self._json(409, {"error": "no_tokens", "tokens": _Site.balance})
            return
        _Site.balance -= count
        self._json(200, {"email": "dj@example.com", "tokens": _Site.balance, "deviceToken": ""})


class TokenSpendTests(unittest.TestCase):
    def setUp(self):
        _Site.balance = 3
        _Site.spends = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_address[1]
        self._old_site = os.environ.get("NJR_ACCOUNT_SITE")
        self._old_dir = os.environ.get("NJR_ACCOUNT_DIR")
        os.environ["NJR_ACCOUNT_SITE"] = f"http://127.0.0.1:{port}"
        folder = os.path.join(self.server.server_address and "", "")
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["NJR_ACCOUNT_DIR"] = self.tmp.name
        session = os.path.join(self.tmp.name, "account-session.json")
        with open(session, "w", encoding="utf-8") as handle:
            json.dump({"deviceToken": "abc", "email": "dj@example.com"}, handle)
        pimp_list.set_token_balance(3)
        pimp_list._tokens_spent = 0

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()
        if self._old_site is None:
            os.environ.pop("NJR_ACCOUNT_SITE", None)
        else:
            os.environ["NJR_ACCOUNT_SITE"] = self._old_site
        if self._old_dir is None:
            os.environ.pop("NJR_ACCOUNT_DIR", None)
        else:
            os.environ["NJR_ACCOUNT_DIR"] = self._old_dir

    def test_button_spend_lowers_the_account(self):
        pimp_list.charge_token()
        self.assertEqual(_Site.spends, [1])
        self.assertEqual(_Site.balance, 2)
        self.assertEqual(pimp_list.token_balance(), 2)

    def test_zero_blocks_the_next_job(self):
        _Site.balance = 0
        pimp_list.set_token_balance(0)
        self.assertFalse(pimp_list.has_tokens(1))
        with self.assertRaises(njr_account.AccountError):
            pimp_list.charge_token()
        self.assertEqual(_Site.balance, 0)
        self.assertEqual(pimp_list.token_balance(), 0)

    def test_checkout_asks_for_the_pack(self):
        url = njr_account.checkout_pack("50")
        self.assertTrue(url.startswith("https://checkout.stripe.com/"))


if __name__ == "__main__":
    unittest.main()
