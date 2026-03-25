#!/usr/bin/env python3
"""
Sprawdza, czy ścieżki plików w master.db Rekordbox wskazują na istniejące pliki.
Pomaga zdiagnozować, dlaczego RB pokazuje utwory jako „brak pliku" (czerwone ikony).

Uruchom (RB zamknięty):
  python scripts/verify_rb_paths.py [ścieżka_do_master.db]

Domyślnie:
  Mac:     ~/Library/Pioneer/rekordbox/master.db
  Windows: %APPDATA%\\Pioneer\\rekordbox\\master.db
"""
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _default_rb_db_dir() -> Path:
    """Domyślny katalog bazy Rekordbox w zależności od systemu."""
    home = Path.home()
    if platform.system() == "Windows":
        return home / "AppData" / "Roaming" / "Pioneer" / "rekordbox"
    return home / "Library" / "Pioneer" / "rekordbox"


def main():
    rb_dir = _default_rb_db_dir()
    db_path = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else rb_dir / "master.db"

    if not db_path.exists():
        print("Nie znaleziono:", db_path)
        print("Użycie: python verify_rb_paths.py [ścieżka_do_master.db]")
        return 1

    try:
        from pyrekordbox.db6.database import Rekordbox6Database
        from sqlalchemy import text
    except ImportError as e:
        print("Błąd:", e)
        print("Zainstaluj: pip install pyrekordbox sqlalchemy")
        return 1

    print("=" * 70)
    print("Weryfikacja ścieżek w:", db_path)
    print("=" * 70)

    try:
        db = Rekordbox6Database(str(db_path), unlock=True)
    except Exception as e:
        print("Nie można otworzyć bazy (może wymagać RB do odszyfrowania):", e)
        return 1

    with db.engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM djmdContent"))
        total = r.scalar()
        if total == 0:
            print("\nBaza jest pusta (0 utworów w djmdContent).")
            return 0

        r = conn.execute(text(
            "SELECT ID, Title, FolderPath, FileNameL FROM djmdContent"
        ))
        rows = r.fetchall()

    exists = 0
    missing = []
    sample_paths = []

    for row in rows:
        folder = (row[2] or "").rstrip("/")
        fname = row[3] or ""
        full_path = f"{folder}/{fname}".replace("\\", "/").replace("//", "/")
        if Path(full_path).exists():
            exists += 1
            if len(sample_paths) < 3:
                sample_paths.append(("OK", full_path))
        else:
            if len(missing) < 10:
                missing.append(full_path)
            if len(sample_paths) < 5 and not any(p[1] == full_path for _, p in sample_paths):
                sample_paths.append(("BRAK", full_path))

    print(f"\nUtwory w bazie: {total}")
    print(f"Pliki istnieją:  {exists}")
    print(f"Pliki brak:      {total - exists}")

    if total - exists > 0:
        print("\n--- Przykładowe ścieżki (pierwsze 5) ---")
        for status, p in sample_paths[:5]:
            print(f"  [{status}] {p[:80]}{'...' if len(p) > 80 else ''}")

        print("\n--- Pierwsze 5 brakujących ---")
        for p in missing[:5]:
            print(f"  {p[:80]}{'...' if len(p) > 80 else ''}")

        print("\n>>> Jeśli ścieżki są z innego systemu (np. Windows):")
        print("    Użyj pathFrom / pathTo w konwerterze przed Sync.")
        print("    np. pathFrom: D:\\muzyka  →  pathTo: /Users/test/Desktop/muzyka dj")
    else:
        print("\n✓ Wszystkie ścieżki wskazują na istniejące pliki.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
