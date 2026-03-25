#!/usr/bin/env python3
"""
Tworzy testowy backup VDJ (ZIP) z kilkoma rekordami.
Zawiera: database.xml + TestList.vdjfolder
Ścieżki wskazują na pliki MP3 z VoteBattle.

Użycie:
  python scripts/create_test_vdj_zip.py [--output plik.zip]

Następnie w konwerterze:
  1. Załaduj ten ZIP (VDJ: plik ZIP)
  2. Wybierz szablon RB
  3. Sync do RB (bez pathFrom/pathTo – ścieżki są już poprawne)
  4. Porównaj z manifestem w ZIP
"""
import argparse
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VOTEBATTLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEST_FILES = [
    (VOTEBATTLE_ROOT / "public/uploads/1770813410399-zar_tropikow.mp3", "TEST_VDJ_001", "VoteBattle_Zar"),
    (VOTEBATTLE_ROOT / "public/uploads/1770812911057-muminki.mp3", "TEST_VDJ_002", "VoteBattle_Muminki"),
    (VOTEBATTLE_ROOT / "public/uploads/sfx/seabattle.mp3", "TEST_VDJ_003", "VoteBattle_Seabattle"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", "-o", default="test-backup-vdj.zip", help="Plik ZIP wyjściowy")
    args = ap.parse_args()

    # Sprawdź pliki
    songs_data = []
    for fp, title, artist in TEST_FILES:
        path = str(fp.resolve()).replace("\\", "/")
        if fp.exists():
            songs_data.append((path, title, artist))
        else:
            print(f"Pomijam (nie istnieje): {path}")

    if not songs_data:
        print("Brak plików. Sprawdź ścieżkę VoteBattle.")
        return 1

    # database.xml
    root = ET.Element("VirtualDJ_Database", Version="8.0")
    for path, title, artist in songs_data:
        song = ET.Element("Song", FilePath=path, FileSize="0", Flag="0")
        tags = ET.SubElement(song, "Tags", {
            "Author": artist,
            "Title": title,
            "Genre": "#TEST",
            "Bpm": "120",
            "Key": "C",
        })
        root.append(song)
    tree = ET.ElementTree(root)
    ET.indent(tree, space=" ", level=0)
    import io
    db_xml = io.BytesIO()
    tree.write(db_xml, encoding="utf-8", xml_declaration=True, method="xml", default_namespace="")
    db_xml_bytes = db_xml.getvalue()

    # TestList.vdjfolder – playlist z tymi utworami
    paths_for_playlist = [p for p, _, _ in songs_data]
    vdjfolder = ET.Element("VirtualFolder", Name="TestList")
    for path in paths_for_playlist:
        ET.SubElement(vdjfolder, "song", path=path)
    vdjfolder_xml = ET.tostring(vdjfolder, encoding="unicode")
    # VirtualDJ format – może wymagać innej struktury
    vdjfolder_content = f'<?xml version="1.0"?>\n{vdjfolder_xml}'

    # Manifest
    manifest = [
        "MANIFEST – dane w testowym backupie VDJ",
        "=" * 50,
        "",
        "database.xml – utwory:",
    ]
    for path, title, artist in songs_data:
        manifest.append(f"  Path: {path}")
        manifest.append(f"  Title: {title}, Artist: {artist}")
        manifest.append(f"  Exists: {Path(path).exists()}")
        manifest.append("")
    manifest.append("TestList.vdjfolder – playlist z powyższymi ścieżkami")
    manifest_text = "\n".join(manifest)

    # ZIP
    out_path = Path(args.output)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("database.xml", db_xml_bytes)
        zf.writestr("TestList.vdjfolder", vdjfolder_content)
        zf.writestr("MANIFEST.txt", manifest_text)

    print(f"Utworzono: {out_path}")
    print("Zawartość: database.xml, TestList.vdjfolder, MANIFEST.txt")
    print("")
    print("W konwerterze:")
    print("  1. Załaduj ten ZIP (VDJ: plik ZIP)")
    print("  2. Szablon RB: wybierz backup RB")
    print("  3. Sync do RB (ścieżki są bezwzględne – bez pathFrom/pathTo)")
    print("  4. Porównaj RB z MANIFEST.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
