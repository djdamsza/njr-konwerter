#!/usr/bin/env python3
"""Otwieranie bazy (Serato/VDJ) i eksport ZIP."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("FLASK_ENV", "testing")

from serato_parser import _encode_utf16be, _write_serato_record  # noqa: E402

from app import app  # noqa: E402
import app_state as st  # noqa: E402


def _otrk(path: str) -> bytes:
    buf = io.BytesIO()
    _write_serato_record(buf, "pfil", _encode_utf16be(path))
    _write_serato_record(buf, "tsng", _encode_utf16be("Song"))
    _write_serato_record(buf, "tart", _encode_utf16be("Artist"))
    return buf.getvalue()


def _serato_db(*otrks: bytes) -> bytes:
    buf = io.BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    for o in otrks:
        _write_serato_record(buf, "otrk", o)
    return buf.getvalue()


def _serato_crate(path: str) -> bytes:
    buf = io.BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Crate"))
    inner = io.BytesIO()
    _write_serato_record(inner, "ptrk", _encode_utf16be(path))
    _write_serato_record(buf, "otrk", inner.getvalue())
    return buf.getvalue()


def _vdj_xml(path: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<VirtualDJ_Database Version="801">\n'
        f'<Song FilePath="{path}"><Tags Title="T" Author="A"/></Song>\n'
        "</VirtualDJ_Database>\n"
    ).encode("utf-8")


class TestLoadAndExport(unittest.TestCase):
    def setUp(self):
        st.reset_session()
        self.account = tempfile.TemporaryDirectory()
        os.environ["NJR_ACCOUNT_DIR"] = self.account.name
        (Path(self.account.name) / "account-session.json").write_text(
            json.dumps({"deviceToken": "test-device", "email": "test@example.com"}),
            encoding="utf-8",
        )
        self.client = app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / "track.mp3"
        self.audio.write_bytes(b"ID3")
        rel = "Users/test/Music/track.mp3"
        self.music = self.root / "Music"
        serato = self.music / "_Serato_"
        sub = serato / "Subcrates"
        sub.mkdir(parents=True)
        (serato / "database V2").write_bytes(_serato_db(_otrk(str(self.audio))))
        (sub / "Nowe.crate").write_bytes(_serato_crate(str(self.audio)))
        self.serato_dir = serato
        self.db_file = serato / "database V2"

    def tearDown(self):
        st.reset_session()
        self.tmp.cleanup()
        self.account.cleanup()
        os.environ.pop("NJR_ACCOUNT_DIR", None)

    def test_load_serato_file_folder_parent(self):
        for p in (self.db_file, self.serato_dir, self.music):
            st.reset_session()
            r = self.client.post("/api/load", json={"path": str(p)})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            d = r.get_json()
            self.assertEqual(d["source"], "serato")
            self.assertGreaterEqual(d["count"], 1)
            self.assertGreaterEqual(d.get("playlists") or 0, 1)

    def test_load_serato_nested_zip_and_export(self):
        zpath = self.root / "pack.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("backup/_Serato_/database V2", self.db_file.read_bytes())
            zf.writestr("backup/_Serato_/Subcrates/Nowe.crate", (self.serato_dir / "Subcrates" / "Nowe.crate").read_bytes())
        r = self.client.post("/api/load", json={"path": str(zpath)})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["source"], "serato")

        exp = self.client.get("/api/export-serato?cratesOnly=0")
        self.assertEqual(exp.status_code, 200, exp.headers.get("Content-Type"))
        self.assertIn("zip", (exp.headers.get("Content-Type") or "").lower())
        names = zipfile.ZipFile(io.BytesIO(exp.data)).namelist()
        self.assertTrue(any(n.endswith("database V2") for n in names), names)
        self.assertTrue(any(n.endswith(".crate") for n in names), names)

        vdj = self.client.get("/api/download")
        self.assertEqual(vdj.status_code, 200)
        vnames = zipfile.ZipFile(io.BytesIO(vdj.data)).namelist()
        self.assertIn("database.xml", vnames)

    def test_load_vdj_zip_still_works(self):
        zpath = self.root / "vdj.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("database.xml", _vdj_xml(str(self.audio)))
            zf.writestr(
                "MyLists/nowe.vdjfolder",
                f'<VirtualFolder><song path="{self.audio}"/></VirtualFolder>',
            )
        r = self.client.post("/api/load", json={"path": str(zpath)})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual(d["source"], "vdj")
        self.assertGreaterEqual(d["count"], 1)
        exp = self.client.get("/api/export-serato?cratesOnly=1")
        self.assertEqual(exp.status_code, 200, exp.headers.get("Content-Type"))

    def test_load_universal_database_v2_filename(self):
        with self.db_file.open("rb") as f:
            r = self.client.post(
                "/api/load-universal",
                data={"file": (f, "database V2")},
                content_type="multipart/form-data",
            )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["source"], "serato")

    def test_crate_file_rejected(self):
        crate = self.serato_dir / "Subcrates" / "Nowe.crate"
        r = self.client.post("/api/load", json={"path": str(crate)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("crate", (r.get_json() or {}).get("error", "").lower())


if __name__ == "__main__":
    unittest.main()
