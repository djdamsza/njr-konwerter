"""Tagi przy podmianie zawsze, cue tylko przy tym samym czasie."""
import unittest

from replace_inherit import inherit_record, same_length


def _song(**extra):
    base = {
        "Infos.SongLength": "200",
        "Tags.Genre": "",
        "Tags.User1": "",
        "Tags.User2": "",
        "Tags.Bpm": "",
        "Tags.Key": "",
        "_children_xml": [],
    }
    base.update(extra)
    return base


class InheritTests(unittest.TestCase):
    def test_same_length_copies_cues_bpm_and_key(self):
        source = _song(
            **{
                "Tags.User1": "#lato",
                "Tags.Bpm": "0.5",
                "Tags.Key": "8A",
                "_children_xml": [
                    '<Poi Type="beatgrid" Pos="0.1" Bpm="120" />',
                    '<Poi Name="A" Pos="10" Num="1" Type="cue" />',
                    '<Poi Name="B" Pos="40" Num="2" Type="cue" />',
                ],
            }
        )
        dest = _song(**{"_children_xml": ['<Poi Name="stary" Pos="1" Num="0" Type="cue" />']})
        notes = inherit_record(source, dest)
        self.assertTrue(notes["sameLength"])
        self.assertTrue(notes["cues"])
        self.assertTrue(notes["tags"])
        self.assertTrue(notes["bpm"])
        self.assertTrue(notes["key"])
        cues = [xml for xml in dest["_children_xml"] if 'type="cue"' in xml.lower()]
        self.assertEqual(len(cues), 2)
        self.assertNotIn("stary", dest["_children_xml"][0])
        self.assertEqual(dest["Tags.User1"], "#lato")
        self.assertEqual(dest["Tags.Bpm"], "0.5")
        self.assertEqual(dest["Tags.Key"], "8A")

    def test_different_length_keeps_cues_but_takes_tags(self):
        source = _song(
            **{
                "Infos.SongLength": "200",
                "Tags.Genre": "#dance",
                "Tags.Bpm": "0.46",
                "Tags.Key": "1A",
                "_children_xml": ['<Poi Name="A" Pos="10" Num="1" Type="cue" />'],
            }
        )
        dest = _song(
            **{
                "Infos.SongLength": "80",
                "Tags.Bpm": "0.6",
                "Tags.Key": "5B",
                "_children_xml": ['<Poi Name="zostaje" Pos="2" Num="0" Type="cue" />'],
            }
        )
        notes = inherit_record(source, dest)
        self.assertFalse(same_length(source, dest))
        self.assertFalse(notes["cues"])
        self.assertFalse(notes["bpm"])
        self.assertTrue(notes["tags"])
        self.assertEqual(dest["Tags.Genre"], "#dance")
        self.assertEqual(dest["Tags.Bpm"], "0.6")
        self.assertEqual(dest["Tags.Key"], "5B")
        self.assertIn("zostaje", dest["_children_xml"][0])

    def test_tags_are_added_not_wiped(self):
        source = _song(**{"Tags.User2": "#wesele"})
        dest = _song(**{"Infos.SongLength": "30", "Tags.User2": "#pop"})
        inherit_record(source, dest)
        self.assertEqual(dest["Tags.User2"], "#pop #wesele")

    def test_empty_source_tags_do_not_clear_dest(self):
        source = _song()
        dest = _song(**{"Tags.Genre": "#zostaje"})
        notes = inherit_record(source, dest)
        self.assertFalse(notes["tags"])
        self.assertEqual(dest["Tags.Genre"], "#zostaje")


if __name__ == "__main__":
    unittest.main()
