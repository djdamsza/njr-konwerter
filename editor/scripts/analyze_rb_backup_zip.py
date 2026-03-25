#!/usr/bin/env python3
"""
Analiza struktury backupu Rekordbox (ZIP z File → Library → Backup Library).
Uruchom: python scripts/analyze_rb_backup_zip.py <ścieżka_do_backup.zip>

Aby utworzyć backup: w Rekordbox File → Library → Backup Library.
"""
import sys
import zipfile
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Użycie: python analyze_rb_backup_zip.py <ścieżka_do_backup.zip>")
        print()
        print("Aby utworzyć backup w Rekordbox:")
        print("  File → Library → Backup Library")
        print("  Zapisz plik .zip na dysk")
        return 1

    zip_path = Path(sys.argv[1]).expanduser().resolve()
    if not zip_path.exists():
        print(f"Plik nie istnieje: {zip_path}")
        return 1

    print("=" * 60)
    print("Struktura backupu Rekordbox:", zip_path)
    print("=" * 60)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        print(f"\nPliki w ZIP ({len(names)}):")
        for name in sorted(names):
            info = zf.getinfo(name)
            size = info.file_size
            print(f"  {name} ({size} B)")
        print(f"\nGłówny poziom:")
        roots = set()
        for name in names:
            parts = name.replace("\\", "/").split("/")
            if parts[0]:
                roots.add(parts[0])
        for r in sorted(roots):
            print(f"  /{r}/")
        if "master.db" in [n.split("/")[-1].split("\\")[-1] for n in names]:
            print("\n✓ master.db znaleziony w backupie")
        else:
            print("\n? master.db nie znaleziony – sprawdź strukturę")

    return 0


if __name__ == "__main__":
    sys.exit(main())
