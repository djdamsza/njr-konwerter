#!/usr/bin/env python3
"""
Tworzy testową bazę Rekordbox z kilkoma rekordami o znanych danych.
Ścieżki wskazują na pliki MP3 z projektu VoteBattle – łatwa weryfikacja.

Użycie:
  python scripts/create_test_rb_db.py [--template ścieżka] [--output folder] [--sync]
  python scripts/create_test_rb_db.py --variants [--sync]   # ten sam plik, różne formaty ścieżki

  --template   backup RB (ZIP) lub master.db – domyślnie ~/Library/Pioneer/rekordbox/master.db
  --output    folder wyjściowy (domyślnie: test-output/)
  --sync      skopiuj master.db do folderu RB
  --variants  jeden plik × 4 warianty ścieżki (01_absolute, 02_file_localhost, 03_file_triple, 04_file_no_leading)
             – sprawdź w RB, który wiersz ma zieloną ikonę

Po uruchomieniu:
  1. Zobacz MANIFEST.txt – co zapisaliśmy (ścieżki, tytuły, artist)
  2. Skopiuj test-output/master.db do ~/Library/Pioneer/rekordbox/ (lub użyj --sync)
  3. Uruchom Rekordbox
  4. Porównaj: czy RB pokazuje te same dane? Czy ikony są czerwone?
"""
import argparse
import sys
from pathlib import Path

# Ścieżka do modułów
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Pliki testowe z VoteBattle (istniejące na dysku)
# scripts/ -> vdj-database-editor -> tools -> VoteBattle
VOTEBATTLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEST_FILE = VOTEBATTLE_ROOT / "public/uploads/1770813410399-zar_tropikow.mp3"  # jeden plik do testu wariantów

# Warianty formatu ścieżki – ten sam plik, różne zapisy (sprawdzimy który zadziała w RB)
def _path_variants(real_path: Path) -> list[tuple[str, str]]:
    """Zwraca [(path_string, title_suffix), ...] – różne warianty zapisu ścieżki."""
    s = str(real_path.resolve())
    return [
        (s, "01_absolute"),                              # /Users/test/Documents/...
        (f"file://localhost{s}", "02_file_localhost"),    # file://localhost/Users/...
        (f"file:///{s.lstrip('/')}", "03_file_triple"),   # file:///Users/...
        (f"file://{s.lstrip('/')}", "04_file_no_leading"),  # file://Users/... (bez / na początku ścieżki)
    ]


def main():
    ap = argparse.ArgumentParser(description="Tworzy testową bazę RB z plikami VoteBattle")
    ap.add_argument("--template", "-t", help="Backup RB (ZIP) lub master.db")
    ap.add_argument("--output", "-o", default="test-output", help="Folder wyjściowy")
    ap.add_argument("--sync", action="store_true", help="Skopiuj do folderu RB")
    ap.add_argument("--variants", "-v", action="store_true",
                    help="Ten sam plik z różnymi formatami ścieżki (01_absolute, 02_file_localhost, …)")
    args = ap.parse_args()

    from unified_model import UnifiedDatabase, Track
    from rb_masterdb_generator import unified_to_master_db

    tracks = []
    if args.variants:
        # Tryb wariantów – jeden plik, różne zapisy ścieżki
        if not TEST_FILE.exists():
            print(f"Plik testowy nie istnieje: {TEST_FILE}")
            return 1
        for path_str, suffix in _path_variants(TEST_FILE):
            tracks.append(Track(path=path_str, title=f"TEST_PATH_{suffix}", artist="Variant", genre="#TEST"))
        print(f"Tryb wariantów: {len(tracks)} wierszy, ten sam plik, różne formaty ścieżki")
    else:
        # Tryb standardowy – kilka plików
        TEST_FILES = [
            (VOTEBATTLE_ROOT / "public/uploads/1770813410399-zar_tropikow.mp3", "TEST_RB_001", "VoteBattle_Zar"),
            (VOTEBATTLE_ROOT / "public/uploads/1770812911057-muminki.mp3", "TEST_RB_002", "VoteBattle_Muminki"),
            (VOTEBATTLE_ROOT / "public/uploads/sfx/seabattle.mp3", "TEST_RB_003", "VoteBattle_Seabattle"),
            (VOTEBATTLE_ROOT / "public/familiada/sounds/jingle.mp3", "TEST_RB_004", "VoteBattle_Jingle"),
            (VOTEBATTLE_ROOT / "public/familiada/sounds/correct.mp3", "TEST_RB_005", "VoteBattle_Correct"),
        ]
        for fp, title, artist in TEST_FILES:
            path = str(fp.resolve())
            if fp.exists():
                tracks.append(Track(path=path, title=title, artist=artist, genre="#TEST"))
            else:
                print(f"Pomijam (nie istnieje): {path}")

    if not tracks:
        print("Brak plików testowych. Sprawdź ścieżkę VoteBattle.")
        return 1

    db = UnifiedDatabase(tracks=tracks, playlists=[])

    # Szablon
    template = None
    if args.template:
        template = str(Path(args.template).expanduser().resolve())
    else:
        default_rb = Path.home() / "Library" / "Pioneer" / "rekordbox" / "master.db"
        if default_rb.exists():
            template = str(default_rb)
            print(f"Używam szablonu: {template}")
        else:
            print("Brak szablonu. Użyj: --template /ścieżka/do/backupu.zip")
            print("  (File → Library → Backup Library w RB)")
            return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_db = out_dir / "master.db"

    # Generuj
    print(f"Generuję bazę z {len(tracks)} utworami...")
    master_bytes = unified_to_master_db(db, path_replace=None, template_path=template, skip_my_tags=True)
    out_db.write_bytes(master_bytes)

    # Manifest – co zapisaliśmy (do porównania z RB)
    manifest_lines = [
        "=" * 70,
        "MANIFEST – dane zapisane do master.db (test RB)",
        "=" * 70,
        "",
        "Porównaj z tym, co pokazuje Rekordbox po załadowaniu tej bazy.",
        "Jeśli RB pokazuje czerwone ikony – ścieżki są nieprawidłowe.",
        "Jeśli kolumny Artist/Genre puste – RB może czytać z plików.",
        "",
        "--- Utwory ---",
    ]
    for t in tracks:
        manifest_lines.append(f"  Path:     {t.path}")
        manifest_lines.append(f"  Title:   {t.title}")
        manifest_lines.append(f"  Artist:  {t.artist}")
        manifest_lines.append(f"  Exists:  {Path(t.path).exists()}")
        manifest_lines.append("")

    manifest_path = out_dir / "MANIFEST.txt"
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")
    print(f"Zapisano: {out_db}")
    print(f"Manifest: {manifest_path}")

    # Weryfikacja – odczyt z wygenerowanej bazy
    try:
        from pyrekordbox.db6.database import Rekordbox6Database
        from sqlalchemy import text
        rb = Rekordbox6Database(str(out_db), unlock=True)
        with rb.engine.connect() as conn:
            r = conn.execute(text(
                "SELECT Title, FolderPath, FileNameL FROM djmdContent"
            ))
            rows = list(r)
        manifest_lines.append("--- Odczyt z master.db (djmdContent) ---")
        for row in rows:
            manifest_lines.append(f"  Title: {row[0]}")
            manifest_lines.append(f"  FolderPath: {row[1]}")
            manifest_lines.append(f"  FileNameL: {row[2]}")
            # RB: FolderPath = pełna ścieżka gdy kończy się na FileNameL
            fp, fn = row[1] or "", row[2] or ""
            full = fp if (fp and fn and fp.endswith(fn)) else fp.rstrip("/") + "/" + fn
            manifest_lines.append(f"  Full path exists: {Path(full).exists()}")
            manifest_lines.append("")
        manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

        # contentFile
        with rb.engine.connect() as conn:
            r = conn.execute(text("SELECT ContentID, Path, LENGTH(Path) FROM contentFile"))
            cf_rows = list(r)
        manifest_lines.append("--- contentFile ---")
        for row in cf_rows:
            manifest_lines.append(f"  ContentID: {row[0]}, Path len: {row[2]}")
            manifest_lines.append(f"  Path: {row[1]}")
            manifest_lines.append(f"  Exists: {Path(row[1]).exists() if row[1] else False}")
            manifest_lines.append("")
        manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")
    except Exception as e:
        manifest_lines.append(f"Błąd weryfikacji: {e}")
        manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

    if args.sync:
        rb_folder = Path.home() / "Library" / "Pioneer" / "rekordbox"
        if rb_folder.exists():
            import shutil
            dest = rb_folder / "master.db"
            shutil.copy2(out_db, dest)
            # Usuń WAL
            for suf in ("-wal", "-shm"):
                (rb_folder / f"master.db{suf}").unlink(missing_ok=True)
            print(f"Skopiowano do: {dest}")
            print("ZAMKNIJ Rekordbox przed sync! Uruchom RB i porównaj z manifestem.")
        else:
            print("Folder RB nie istnieje:", rb_folder)

    return 0


if __name__ == "__main__":
    sys.exit(main())
