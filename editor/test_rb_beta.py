"""Testy RB Beta — skan folderów, duplikaty, wersje."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app import app
import app_state as st


class TestRbBeta(unittest.TestCase):
    def setUp(self):
        st.reset_session()
        self.tmp = tempfile.mkdtemp(prefix='njr_rb_beta_')
        self.client = app.test_client()

    def tearDown(self):
        st.reset_session()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_mp3_stub(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_scan_folders_and_hash_duplicates(self):
        root = Path(self.tmp)
        a = root / 'a' / 'song.mp3'
        b = root / 'b' / 'song_copy.mp3'
        payload = b'ID3' + b'\x00' * 100 + b'same-audio-content'
        self._write_mp3_stub(a, payload)
        self._write_mp3_stub(b, payload)

        r = self.client.post('/api/rb-beta/scan-folders', json={
            'folderPaths': [str(root)],
            'computeHash': True,
        })
        self.assertEqual(r.status_code, 200, r.get_json())
        data = r.get_json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('count'), 2)
        self.assertEqual(st.source, 'folder_beta')

        dup = self.client.get('/api/duplicates?method=hash&scope=files')
        self.assertEqual(dup.status_code, 200)
        d = dup.get_json()
        self.assertGreaterEqual(len(d.get('groups') or []), 1)
        self.assertGreaterEqual(d.get('totalDuplicates', 0), 1)

    def test_remix_versions_mode(self):
        root = Path(self.tmp)
        f1 = root / 'Artist - Song (Radio Edit).mp3'
        f2 = root / 'Artist - Song (Club Mix).mp3'
        self._write_mp3_stub(f1, b'ID3' + b'\x01' * 80)
        self._write_mp3_stub(f2, b'ID3' + b'\x02' * 80)

        st.load_folder_beta([str(root)])
        for i, s in enumerate(st.songs):
            if i == 0:
                s['Tags.Author'] = 'Test Artist'
                s['Tags.Title'] = 'My Song (Radio Edit)'
            else:
                s['Tags.Author'] = 'Test Artist'
                s['Tags.Title'] = 'My Song (Club Mix)'

        r = self.client.get('/api/remixes?mode=versions')
        self.assertEqual(r.status_code, 200)
        groups = r.get_json().get('groups') or []
        self.assertGreaterEqual(len(groups), 1)
        self.assertEqual(groups[0].get('kind'), 'versions')

    def test_delete_files_removes_from_session(self):
        root = Path(self.tmp)
        f = root / 'del_me.mp3'
        self._write_mp3_stub(f, b'ID3delete')
        st.load_folder_beta([str(root)])
        path = st.songs[0]['FilePath']
        self.assertTrue(Path(path).exists())

        r = self.client.post('/api/rb-beta/delete-files', json={'paths': [path]})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d.get('deleted'), 1)
        self.assertEqual(len(st.songs), 0)
        self.assertFalse(Path(path).exists())


if __name__ == '__main__':
    unittest.main()
