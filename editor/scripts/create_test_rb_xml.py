#!/usr/bin/env python3
"""
Generuje rekordbox.xml z jednym utworem VoteBattle – do testu importu XML.
RB: File → Import → Rekordbox → wybierz ten plik.

Jeśli import XML zadziała (zielona ikona), problem leży w master.db, nie w ścieżce.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VOTEBATTLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEST_FILE = VOTEBATTLE_ROOT / "public/uploads/1770813410399-zar_tropikow.mp3"


def main():
    if not TEST_FILE.exists():
        print(f"Plik nie istnieje: {TEST_FILE}")
        return 1

    from unified_model import UnifiedDatabase, Track
    from rb_generator import generate_rb_xml

    track = Track(
        path=str(TEST_FILE.resolve()),
        title="TEST_XML_IMPORT",
        artist="VoteBattle",
        genre="#TEST",
    )
    db = UnifiedDatabase(tracks=[track], playlists=[])

    xml_bytes = generate_rb_xml(db)
    out = Path("test-output/rekordbox-import-test.xml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(xml_bytes)

    print(f"Zapisano: {out}")
    print()
    print("W Rekordbox: File → Import → Rekordbox")
    print("Wybierz ten plik XML.")
    print()
    print("Jeśli utwór ma zieloną ikonę – import XML działa, problem jest w master.db.")
    print("Jeśli czerwona – RB nie akceptuje tej ścieżki także przez XML.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
