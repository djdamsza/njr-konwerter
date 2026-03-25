#!/usr/bin/env python3
"""
Faza A – analiza struktury bazy Rekordbox (master.db).
Uruchom: python scripts/analyze_rb_db.py [ścieżka_do_master.db]
Domyślnie: ~/Library/Pioneer/rekordbox/master.db lub master.backup3.db
"""
import os
import sys
from pathlib import Path

# Dodaj ścieżkę do modułów
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    rb_dir = Path.home() / "Library" / "Pioneer" / "rekordbox"
    db_path = None
    
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1]).expanduser().resolve()
    else:
        for name in ["master.db", "master.backup3.db", "master.backup2.db", "master.backup1.db"]:
            p = rb_dir / name
            if p.exists():
                db_path = p
                break
    
    if not db_path or not db_path.exists():
        print("Nie znaleziono master.db. Użycie: python analyze_rb_db.py [ścieżka]")
        print("Domyślna lokalizacja:", rb_dir)
        return 1
    
    print("=" * 60)
    print("Analiza bazy Rekordbox:", db_path)
    print("=" * 60)
    
    from pyrekordbox.db6.database import Rekordbox6Database
    from sqlalchemy import inspect, text
    
    db = Rekordbox6Database(str(db_path))
    
    # Wszystkie tabele
    insp = inspect(db.engine)
    tables = insp.get_table_names()
    print(f"\nTabele ({len(tables)}):")
    for t in sorted(tables):
        print(f"  {t}")
    
    # Kluczowe tabele – schemat i liczba rekordów
    key_tables = [
        "djmdContent", "djmdArtist", "djmdAlbum", "djmdGenre", "djmdKey",
        "djmdPlaylist", "djmdSongPlaylist", "djmdCue", "contentCue", "contentFile"
    ]
    
    with db.engine.connect() as conn:
        for table in key_tables:
            if table not in tables:
                print(f"\n[?] Tabela {table} nie istnieje")
                continue
            cols = [c["name"] for c in insp.get_columns(table)]
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"\n--- {table} ({count} rekordów) ---")
            print("Kolumny:", ", ".join(cols[:15]), "..." if len(cols) > 15 else "")
            
            if count > 0 and table == "djmdContent":
                result = conn.execute(text(
                    f"SELECT ID, Title, FolderPath, FileNameL, BPM, Length, ArtistID, GenreID FROM {table} LIMIT 3"
                ))
                for row in result:
                    print("  Przykład:", row)
            elif count > 0 and table == "djmdPlaylist":
                result = conn.execute(text(
                    f"SELECT ID, Name, Seq, ParentID, Attribute FROM {table} LIMIT 5"
                ))
                for row in result:
                    print("  Przykład:", row)
            elif count > 0 and table == "djmdSongPlaylist":
                result = conn.execute(text(
                    f"SELECT ID, PlaylistID, ContentID, TrackNo FROM {table} LIMIT 5"
                ))
                for row in result:
                    print("  Przykład:", row)
    
    # Sprawdź czy pyrekordbox ma modele do dodawania
    print("\n" + "=" * 60)
    print("pyrekordbox – dostępne modele/klasy:")
    import pyrekordbox.db6 as db6
    for name in dir(db6):
        if not name.startswith("_"):
            print(f"  db6.{name}")
    
    # Sprawdź czy można tworzyć nową bazę
    print("\n" + "=" * 60)
    print("Sprawdzenie API – czy można dodawać rekordy:")
    try:
        from pyrekordbox.db6 import tables as rb_tables
        if hasattr(rb_tables, "DjmdContent"):
            print("  DjmdContent model istnieje")
        if hasattr(db, "session"):
            print("  db.session istnieje")
    except Exception as e:
        print("  Błąd:", e)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
