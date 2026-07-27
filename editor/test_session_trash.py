"""Testy kosza sesji."""
from __future__ import annotations

import unittest

import app_state as st
import session_trash as trash


class TestSessionTrash(unittest.TestCase):
    def setUp(self):
        st.reset_session()
        st.songs = [{
            'FilePath': '/music/a.mp3',
            'Tags.Author': 'Artist',
            'Tags.Title': 'Song A',
        }]

    def tearDown(self):
        st.reset_session()

    def test_add_and_restore_db_track(self):
        song = st.songs[0]
        trash.add_db_track_trash(song, original_index=0, source='test')
        st.songs.clear()
        self.assertEqual(len(st.trash_items), 1)
        result = trash.restore_items([st.trash_items[0]['id']])
        self.assertEqual(result['restored'], 1)
        self.assertEqual(len(st.songs), 1)
        self.assertEqual(st.songs[0]['Tags.Title'], 'Song A')

    def test_dismiss_removes_from_active_list(self):
        trash.add_db_track_trash(st.songs[0], original_index=0)
        item_id = st.trash_items[0]['id']
        st.songs.clear()
        trash.dismiss_items([item_id])
        active = trash.list_trash(active_only=True)
        self.assertEqual(len(active), 0)

    def test_summary_counts(self):
        trash.add_file_trash('/music/x.mp3')
        trash.add_db_track_trash(st.songs[0], original_index=0)
        s = trash.trash_summary()
        self.assertEqual(s['count'], 2)
        self.assertEqual(s['files'], 1)
        self.assertEqual(s['tracks'], 1)


if __name__ == '__main__':
    unittest.main()
