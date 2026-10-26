"""Oferta aktualizacji tylko ze strony Nowa Jakość Rozrywki."""
from __future__ import annotations

import unittest

import updater


def payload(version="1.0.14", url=None, sha="ab" * 32, slot="macArm"):
    name = updater.asset_name(version, slot)
    body = {
        "version": version,
        "changelog": "Nowa lista.\nDruga linia.",
        "windows": {"url": "", "sha256": ""},
        "macArm": {"url": "", "sha256": ""},
        "macIntel": {"url": "", "sha256": ""},
    }
    body[slot] = {
        "url": url or f"https://nowajakoscrozrywki.pl/pobierz/{name}",
        "sha256": sha,
    }
    return body


class UpdateOfferTests(unittest.TestCase):
    def test_newer_file_on_the_site_is_offered(self):
        offer = updater.select_offer(payload(), "1.0.13", "macArm")
        self.assertEqual(offer["version"], "1.0.14")
        self.assertEqual(offer["name"], "Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg")
        self.assertTrue(offer["url"].startswith("https://nowajakoscrozrywki.pl/pobierz/"))

    def test_same_or_older_version_is_silent(self):
        self.assertIsNone(updater.select_offer(payload(version="1.0.13"), "1.0.13", "macArm"))
        self.assertIsNone(updater.select_offer(payload(version="1.0.12"), "1.0.13", "macArm"))
        self.assertIsNone(updater.select_offer(payload(version="0.0.0"), "1.0.13", "macArm"))

    def test_github_and_other_hosts_are_rejected(self):
        bad = payload(url="https://github.com/djdamsza/njr-konwerter/releases/download/v1.0.14/Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg")
        self.assertIsNone(updater.select_offer(bad, "1.0.13", "macArm"))
        http = payload(url="http://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg")
        self.assertIsNone(updater.select_offer(http, "1.0.13", "macArm"))

    def test_site_name_njr_konwerter_is_offered(self):
        url = "https://nowajakoscrozrywki.pl/pobierz/NJR-konwerter-1.1.0-windows-x64.exe"
        offer = updater.select_offer(payload(version="1.1.0", url=url, slot="windows"), "1.0.16", "windows")
        self.assertEqual(offer["version"], "1.1.0")
        self.assertEqual(offer["name"], "NJR-konwerter-1.1.0-windows-x64.exe")

    def test_wrong_filename_or_checksum_is_rejected(self):
        wrong_name = payload(url="https://nowajakoscrozrywki.pl/pobierz/inny-plik.dmg")
        self.assertIsNone(updater.select_offer(wrong_name, "1.0.13", "macArm"))
        self.assertIsNone(updater.select_offer(payload(sha="za-krotka"), "1.0.13", "macArm"))

    def test_other_slot_is_not_used(self):
        self.assertIsNone(updater.select_offer(payload(slot="windows"), "1.0.13", "macArm"))


if __name__ == "__main__":
    unittest.main()
