"""
Obsługa plików .vdjfolder (Filter Folders VirtualDJ).
Aktualizacja filtrów przy scalaniu i usuwaniu tagów.
Konwersja filter list → zwykłe playlisty (dla Serato, RB itd.).
"""
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict, Set, TYPE_CHECKING


def remove_paths_from_vdjfolder_content(content: str, paths_to_remove: Set[str]) -> Tuple[str, int]:
    """
    Usuwa z zawartości vdjfolder wszystkie <song path="...">, których znormalizowana ścieżka
    jest w paths_to_remove. Zwraca (nowa_zawartość, liczba_usuniętych_wpisów).
    """
    if not content or not paths_to_remove:
        return content, 0
    try:
        root = ET.fromstring(content)
        if root.tag != "VirtualFolder":
            return content, 0
        to_remove = []
        for song in root.findall("song"):
            p = (song.get("path") or "").strip()
            if normalize_path(p) in paths_to_remove:
                to_remove.append(song)
        for elem in to_remove:
            root.remove(elem)
        if not to_remove:
            return content, 0
        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
        return out, len(to_remove)
    except ET.ParseError:
        return content, 0

if TYPE_CHECKING:
    from unified_model import Playlist


def normalize_path(p: str) -> str:
    """
    Normalizuje ścieżkę do porównań (vdjfolder vs database.xml).
    - Zamiana \\ na /
    - Unicode NFC (ważne na macOS – łączenie znaków diakrytycznych)
    - Usunięcie białych znaków
    """
    if not p or not p.strip():
        return ""
    p = p.replace("\\", "/").strip()
    p = unicodedata.normalize("NFC", p)
    return p


def _tag_for_filter(tag: str) -> str:
    """Tag w formacie filtra (bez #, uppercase dla has tag)."""
    t = tag.strip().lstrip('#')
    return t


def _tag_variants(tag: str) -> List[str]:
    """Warianty tagu do dopasowania."""
    t = tag.strip()
    base = t.lstrip('#')
    return [base, t, base.upper(), t.upper(), '#' + base, '#' + base.upper()]


def update_filter_merge(filter_text: str, replacements: List[Tuple[str, str]], new_tag: str, target_field: str) -> str:
    """
    replacements: [(field, old_tag), ...] - tagi do zastąpienia
    new_tag: nowy tag
    target_field: Genre|User1|User2 - gdzie zapisać
    Zamienia wszystkie wystąpienia starych tagów na nowy w docelowym polu.
    """
    field_to_vdj = {'User1': 'User 1', 'User2': 'User 2', 'Genre': 'Genre'}
    target_vdj = field_to_vdj.get(target_field, target_field)
    new_clean = _tag_for_filter(new_tag)
    repl_has = f'{target_vdj} has tag {new_clean}'
    repl_contains = f'{target_vdj} contains {new_clean}'
    repl_is = f'Genre is #{new_clean}'

    result = filter_text
    for field, old_tag in replacements:
        fvdj = field_to_vdj.get(field, field)
        for v in _tag_variants(old_tag):
            v_clean = v.lstrip('#')
            result = re.sub(rf'{re.escape(fvdj)}\s+has\s+tag\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$|and|or)', repl_has, result, flags=re.IGNORECASE)
            result = re.sub(rf'{re.escape(fvdj)}\s+contains\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$|and|or)', repl_contains, result, flags=re.IGNORECASE)
            result = re.sub(rf'Genre\s+is\s+["\']?#?{re.escape(v_clean)}["\']?(?=\s|$|and|or)', repl_is, result, flags=re.IGNORECASE)
    return result


def update_filter_remove(filter_text: str, field: str, tags: List[str]) -> str:
    """Usuwa warunki z tagami z filtra."""
    field_to_vdj = {'User1': 'User 1', 'User2': 'User 2', 'Genre': 'Genre'}
    fvdj = field_to_vdj.get(field, field)
    result = filter_text

    for tag in tags:
        for v in _tag_variants(tag):
            v_clean = v.lstrip('#')
            # Usuń cały blok "User 1 has tag X" wraz z and/or
            result = re.sub(rf'\s*and\s+{re.escape(fvdj)}\s+has\s+tag\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$)', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'\s*or\s+{re.escape(fvdj)}\s+has\s+tag\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$)', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'{re.escape(fvdj)}\s+has\s+tag\s+["\']?{re.escape(v_clean)}["\']?(?=\s+and\s+|\s+or\s+|$)\s*(and\s+|or\s+)?', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'\s*and\s+{re.escape(fvdj)}\s+contains\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$)', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'\s*or\s+{re.escape(fvdj)}\s+contains\s+["\']?{re.escape(v_clean)}["\']?(?=\s|$)', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'{re.escape(fvdj)}\s+contains\s+["\']?{re.escape(v_clean)}["\']?(?=\s+and\s+|\s+or\s+|$)\s*(and\s+|or\s+)?', '', result, flags=re.IGNORECASE)
            result = re.sub(rf'Genre\s+is\s+["\']?{re.escape(v_clean)}["\']?(?=\s+and\s+|\s+or\s+|$)\s*(and\s+|or\s+)?', '', result, flags=re.IGNORECASE)

    result = re.sub(r'^\s*(and|or)\s+', '', result)
    result = re.sub(r'\s+(and|or)\s*$', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def _is_exportable_path(p: str) -> bool:
    """Czy ścieżka nadaje się do eksportu. netsearch://td... = Tidal streaming (VDJ pobiera z sieci)."""
    if not p or not (p := p.strip()):
        return False
    if p.startswith("netsearch://td"):
        return True
    if p.startswith("netsearch:"):
        return False
    return True


def _is_offline_path(p: str) -> bool:
    """Czy ścieżka to plik offline (nie streaming). M3U obsługuje tylko pliki – td..., spotify: nie działają."""
    if not _is_exportable_path(p):
        return False
    p = p.strip()
    if re.match(r"^td\d+$", p, re.I):
        return False
    if re.match(r"^(spotify:|yt:)[a-zA-Z0-9_-]+$", p):
        return False
    return True


def _xml_attr(val: str) -> str:
    """Escape dla atrybutów XML: & < > \" '."""
    if val is None:
        return ""
    s = str(val)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def create_vdjfolder_playlist(paths: List[str], name: str = "", entries: List[dict] = None) -> str:
    """
    Tworzy XML vdjfolder w formacie VDJ (jak eksport z VirtualDJ).
    entries: lista {path, artist?, title?, size?, songlength?, bpm?, key?, remix?} – gdy brak, używa paths.
    Format VDJ: <?xml?>, VirtualFolder noDuplicates ordered, song z path size songlength bpm key artist title idx.
    """
    if entries:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<VirtualFolder noDuplicates="no" ordered="yes">']
        for idx, e in enumerate(entries):
            p = (e.get("path") or "").strip()
            if not p or not _is_exportable_path(p):
                continue
            artist = _xml_attr(e.get("artist") or e.get("author") or "")
            title = _xml_attr(e.get("title") or "")
            if not artist or not title:
                fname = p.replace("\\", "/").split("/")[-1]
                if fname and (" - " in fname or " – " in fname):
                    sep = " – " if " – " in fname else " - "
                    parts = fname.rsplit(".", 1)[0].split(sep, 1)
                    if not artist and len(parts) >= 1:
                        artist = _xml_attr(parts[0].strip())
                    if not title and len(parts) >= 2:
                        title = _xml_attr(parts[1].strip())
                if not artist:
                    artist = _xml_attr(fname.rsplit(".", 1)[0] if fname else "")
                if not title:
                    title = artist
            size = str(int(e.get("size") or e.get("FileSize") or 0))
            songlength = str(float(e.get("songlength") or e.get("SongLength") or e.get("duration") or 0))
            bpm = e.get("bpm") or "0"
            try:
                bv = float(bpm)
                bpm = f"{bv:.3f}" if 1 <= bv <= 300 else ("0" if bv == 0 else f"{60 / bv:.3f}")
            except (ValueError, TypeError, ZeroDivisionError):
                bpm = "0"
            key = _xml_attr(e.get("key") or "")
            remix = _xml_attr(e.get("remix") or "")
            path_esc = _xml_attr(p)
            attrs = f'path="{path_esc}" size="{size}" songlength="{songlength}" bpm="{bpm}" key="{key}" artist="{artist}" title="{title}" idx="{idx}"'
            if remix:
                attrs += f' remix="{remix}"'
            if re.match(r"^td\d+$", p, re.I):
                attrs += f' netsearchId="{p}"'
            elif p.startswith("netsearch://td"):
                tid = "td" + p[len("netsearch://td"):].strip()
                attrs += f' netsearchId="{tid}"'
            lines.append(f"\t<song {attrs} />")
        lines.append("</VirtualFolder>")
        return "\r\n".join(lines) + "\r\n"
    root = ET.Element("VirtualFolder", Name=name or "Playlist")
    for p in paths:
        if _is_exportable_path(p):
            ET.SubElement(root, "song", path=p.strip())
    return ET.tostring(root, encoding="unicode", default_namespace="")


def create_m3u_playlist(paths: List[str], name: str = "", extended: bool = True, offline_only: bool = True) -> str:
    """
    Tworzy M3U – uniwersalny format (VDJ, Rekordbox, Serato).
    paths: lista ścieżek.
    offline_only: True = tylko pliki (M3U nie obsługuje td..., spotify: – te formaty działają tylko w vdjfolder).
    extended: True = #EXTM3U + #EXTINF
    """
    lines = ["#EXTM3U"]
    for p in paths:
        if (_is_offline_path(p) if offline_only else _is_exportable_path(p)):
            p = p.strip()
            if extended:
                # #EXTINF:duration,artist - title (duration -1 = nieznany)
                name = p.replace("\\", "/").split("/")[-1]
                lines.append(f"#EXTINF:-1,{name}")
            lines.append(p)
    return "\n".join(lines) + "\n"


def scan_vdjfolders(folder: Path) -> Dict[Path, str]:
    """Skanuje folder i zwraca {path: content} dla plików .vdjfolder."""
    out = {}
    for p in folder.rglob('*.vdjfolder'):
        try:
            out[p] = p.read_text(encoding='utf-8')
        except Exception:
            pass
    return out


def _eval_filter_condition(cond: str, song: dict) -> bool:
    """Sprawdza pojedynczy warunek filtra VDJ (np. 'User 1 has tag X')."""
    from vdj_parser import parse_tags_value
    cond = cond.strip().lower()
    if "has tag" in cond:
        m = re.search(r"(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+[\"']?([^\"'\s]+)", cond, re.I)
        if m:
            tag = m.group(1).strip().lstrip("#").lower()
            if "user 1" in cond or "user1" in cond.replace(" ", ""):
                tags = set(t.lstrip("#").lower() for t in parse_tags_value(song.get("Tags.User1", "")))
                return tag in tags
            if "user 2" in cond or "user2" in cond.replace(" ", ""):
                tags = set(t.lstrip("#").lower() for t in parse_tags_value(song.get("Tags.User2", "")))
                return tag in tags
            if "genre" in cond:
                tags = set(t.lstrip("#").lower() for t in parse_tags_value(song.get("Tags.Genre", "")))
                return tag in tags
    if "contains" in cond:
        m = re.search(r"(?:user\s*1|user\s*2|genre)\s+contains\s+[\"']?([^\"']+)", cond, re.I)
        if m:
            val = m.group(1).strip().lstrip("#").lower()
            if "user 1" in cond or "user1" in cond.replace(" ", ""):
                return val in (song.get("Tags.User1", "") or "").lower()
            if "user 2" in cond or "user2" in cond.replace(" ", ""):
                return val in (song.get("Tags.User2", "") or "").lower()
            if "genre" in cond:
                return val in (song.get("Tags.Genre", "") or "").lower()
    if "genre is" in cond or "genre=" in cond:
        m = re.search(r"genre\s+(?:is|=)\s*[\"']?#?([^\"'\s]+)", cond, re.I)
        if m:
            tag = m.group(1).strip().lstrip("#").lower()
            tags = set(t.lstrip("#").lower() for t in parse_tags_value(song.get("Tags.Genre", "")))
            return tag in tags
    return False


def _song_matches_filter(filter_text: str, song: dict) -> bool:
    """Sprawdza czy utwór pasuje do filtra VDJ (or/and)."""
    if not filter_text or not filter_text.strip():
        return False
    parts = re.split(r"\s+or\s+", filter_text.strip(), flags=re.IGNORECASE)
    for part in parts:
        and_parts = re.split(r"\s+and\s+", part.strip(), flags=re.IGNORECASE)
        if all(_eval_filter_condition(ap, song) for ap in and_parts if ap.strip()):
            return True
    return False


def _is_my_library_path(rel_path: str) -> bool:
    """Czy rel_path należy do dodatku My Library (VDJ) – pomijamy jego zawartość."""
    if not rel_path:
        return False
    return "my library" in rel_path.replace("\\", "/").lower()


def filter_lists_to_regular_playlists(
    vdjfolders: Dict[str, str],
    songs: List[dict],
    valid_paths: Set[str],
) -> List["Playlist"]:
    """
    Konwertuje vdjfoldery (VirtualFolder + FilterFolder) na zwykłe playlisty.
    Filter list (smart listy) są rozwijane do listy ścieżek – dla Serato, RB itd.
    valid_paths: zbiór znormalizowanych ścieżek FilePath z bazy.
    Pomija listy z dodatku My Library.
    """
    from unified_model import Playlist

    playlists: List[Playlist] = []
    path_to_norm = {normalize_path(s.get("FilePath", "") or ""): s.get("FilePath", "") or "" for s in songs}
    path_to_norm = {k: v for k, v in path_to_norm.items() if k and v}

    for rel_path, content in vdjfolders.items():
        if _is_my_library_path(rel_path):
            continue
        name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
        if not name:
            continue
        try:
            root = ET.fromstring(content)
            filt = root.get("filter") or root.get("Filter") or ""
            if not filt and root.tag == "FilterFolder":
                child = root.find("VirtualFolder") or root.find("folder")
                if child is not None:
                    filt = child.get("filter") or child.get("Filter") or ""
            if filt:
                paths = []
                for s in songs:
                    path = (s.get("FilePath") or "").strip()
                    if not path:
                        continue
                    np = normalize_path(path)
                    if np in valid_paths and _song_matches_filter(filt, s):
                        paths.append(path_to_norm.get(np, path))
                if paths:
                    playlists.append(Playlist(name=name, track_ids=paths, is_folder=False))
            elif root.tag in ("VirtualFolder", "FilterFolder"):
                paths = []
                for song_elem in root.findall("song"):
                    p = (song_elem.get("path") or "").strip()
                    if not p or p.startswith("netsearch:") or (p.startswith("td") and ":" not in p):
                        continue
                    np = normalize_path(p)
                    if np in valid_paths:
                        paths.append(path_to_norm.get(np, p))
                if paths:
                    playlists.append(Playlist(name=name, track_ids=paths, is_folder=False))
        except ET.ParseError:
            continue
    return playlists


def vdjfolders_to_playlists(vdjfolders: Dict[str, str], valid_paths: Set[str]) -> List["Playlist"]:
    """
    Parsuje vdjfoldery (VirtualFolder z listą utworów) na playlisty RB.
    valid_paths: zbiór znormalizowanych ścieżek FilePath z bazy (użyj normalize_path).
    Pomija FilterFolder (smart listy), netsearch i My Library.
    """
    from unified_model import Playlist

    playlists = []
    for rel_path, content in vdjfolders.items():
        if _is_my_library_path(rel_path):
            continue
        name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
        if not name:
            continue
        try:
            root = ET.fromstring(content)
            if root.tag != "VirtualFolder":
                continue
            paths = []
            for song in root.findall("song"):
                p = (song.get("path") or "").strip()
                if not p or p.startswith("netsearch:") or (p.startswith("td") and ":" not in p):
                    continue
                np = normalize_path(p)
                if np and np in valid_paths:
                    paths.append(np)
            if paths:
                playlists.append(Playlist(name=name, track_ids=paths, is_folder=False))
        except ET.ParseError:
            continue
    return playlists
