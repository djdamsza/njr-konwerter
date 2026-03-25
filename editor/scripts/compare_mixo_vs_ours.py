#!/usr/bin/env python3
"""
Porównanie formatu djmdContent: MIXO (działający) vs nasz generator.
Uruchom: python scripts/compare_mixo_vs_ours.py
Wymaga: rekordbox_bak_mixo_extracted/master.db (backup MIXO)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    mixo_db = Path("/Users/test/Documents/rekordbox_bak_mixo_extracted/master.db")
    if not mixo_db.exists():
        print("Brak:", mixo_db)
        return 1

    from pyrekordbox.db6.database import Rekordbox6Database
    from sqlalchemy import text

    db = Rekordbox6Database(str(mixo_db), unlock=True)
    with db.engine.connect() as conn:
        # Schemat djmdContent
        r = conn.execute(text("PRAGMA table_info(djmdContent)"))
        cols = [row[1] for row in r.fetchall()]

        # Jeden rekord MP3 z pełnymi metadanymi
        r = conn.execute(text("""
            SELECT * FROM djmdContent 
            WHERE FileType = 1 AND ArtistID IS NOT NULL AND Title != ''
            LIMIT 1
        """))
        row = r.fetchone()
        if not row:
            print("Brak utworu MP3 z metadanymi w MIXO")
            return 1

        print("=" * 70)
        print("MIXO djmdContent – rekord działający (MP3 z Artist)")
        print("=" * 70)
        for i, col in enumerate(cols):
            val = row[i]
            if val is not None:
                s = str(val)
                if len(s) > 60:
                    s = s[:57] + "..."
                print(f"  {col:25} = {repr(val)[:70]}")
            else:
                print(f"  {col:25} = NULL")

        # DjmdProperty – DeviceID
        print("\n" + "=" * 70)
        print("DjmdProperty (DeviceID, DBID)")
        print("=" * 70)
        r = conn.execute(text("SELECT * FROM DjmdProperty LIMIT 1"))
        row = r.fetchone()
        if row:
            r2 = conn.execute(text("PRAGMA table_info(DjmdProperty)"))
            pcols = [x[1] for x in r2.fetchall()]
            for i, col in enumerate(pcols):
                if i < len(row):
                    print(f"  {col:25} = {repr(row[i])[:70]}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
