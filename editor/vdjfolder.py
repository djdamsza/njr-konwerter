"""
Obsługa plików .vdjfolder (Filter Folders VirtualDJ).
Aktualizacja filtrów przy scalaniu i usuwaniu tagów.
Konwersja filter list → zwykłe playlisty (dla Serato, RB itd.).
"""
import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict, Set, Optional, TYPE_CHECKING


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
    - Zawalenie // → / w ścieżkach plików (VDJ czasem zapisuje //Users/... jako osobny utwór)
    - Bez ruszania schematów URL (netsearch://, clouddrive://, …)
    - Unicode NFC (ważne na macOS – łączenie znaków diakrytycznych)
    - Usunięcie białych znaków
    """
    if not p or not p.strip():
        return ""
    p = p.replace("\\", "/").strip()
    # Collapse duplicate slashes except after scheme "xxx:"
    if "://" in p:
        scheme, rest = p.split("://", 1)
        while "//" in rest:
            rest = rest.replace("//", "/")
        p = f"{scheme}://{rest}"
    else:
        while "//" in p:
            p = p.replace("//", "/")
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
            p = normalize_path((e.get("path") or "").strip())
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
        np = normalize_path(p.strip()) if p else ""
        if np and _is_exportable_path(np):
            ET.SubElement(root, "song", path=np)
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


def _normalize_filter_text(filt: str) -> str:
    """Normalizuje tekst filtra VDJ (HTML entities, spacje)."""
    return re.sub(r"\s+", " ", html.unescape(filt or "")).strip()


def _is_favorite_folder_content(content: str) -> bool:
    try:
        root = ET.fromstring(content)
        return root.tag == "FavoriteFolder"
    except ET.ParseError:
        return False


def _resolve_vdjfolder_content(
    content: str,
    vdjfolders: Optional[Dict[str, str]] = None,
) -> str:
    """FavoriteFolder → docelowa zawartość listy (np. mylists:/X → MyLists/X)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return content
    if root.tag != "FavoriteFolder":
        return content
    ref = (root.get("path") or root.get("Path") or "").replace("\\", "/").strip()
    if not ref or not vdjfolders:
        return content
    if ref.lower().startswith("mylists:"):
        ref = "MyLists/" + ref.split(":", 1)[1].lstrip("/")
    elif ref.lower().startswith("folders:"):
        ref = "Folders/" + ref.split(":", 1)[1].lstrip("/")
    elif "/" not in ref:
        ref = "MyLists/" + ref
    if ref in vdjfolders:
        return vdjfolders[ref]
    ref_low = ref.lower()
    for key, val in vdjfolders.items():
        if key.lower() == ref_low:
            return val
    return content


def _is_vdj_filter_tree_path(rel_path: str) -> bool:
    """Sideview i Folders/Filters — zdublowane drzewa filtrów VDJ (nie przenosimy do Serato)."""
    if not rel_path:
        return False
    p = rel_path.replace("\\", "/").strip("/").lower()
    if not p:
        return False
    first = p.split("/", 1)[0]
    if first.endswith(".vdjfolder"):
        first = first[: -len(".vdjfolder")]
    if first.endswith(".subfolders"):
        first = first[: -len(".subfolders")]
    return first in ("sideview", "folders", "filters")


def filter_vdjfolders_for_export(vdjfolders: Dict[str, str]) -> Dict[str, str]:
    """
    Lista do eksportu Serato/Engine: pomija My Library, Compatible, Sideview,
    Folders/Filters oraz skróty FavoriteFolder. Zostaje MyLists i pozostałe listy użytkownika.
    """
    out: Dict[str, str] = {}
    for rel_path, content in vdjfolders.items():
        if _is_vdj_filter_tree_path(rel_path):
            continue
        if _is_excluded_from_serato_transfer(rel_path):
            continue
        if _is_favorite_folder_content(content):
            continue
        out[rel_path] = content
    return out


def _is_deck_relative_filter(filt: str) -> bool:
    f = _normalize_filter_text(filt).lower()
    return bool(
        re.search(
            r"\b(bpm\s*difference|bpmdiff|key\s*difference|keydiff|pitch\s*difference)\b",
            f,
        )
    )


def _is_group_by_filter(filt: str) -> bool:
    return _normalize_filter_text(filt).lower().startswith("group by")


def _is_unexportable_filter(filt: str) -> bool:
    """Filtry bez sensownego snapshotu do Serato (Has Links jest eksportowany)."""
    _ = filt  # API zachowane — obecnie wszystkie znane filtry są eksportowalne
    return False


def _song_has_links(song: dict) -> bool:
    """
    Filtr VDJ „Has Links” = Linked Tracks (extra.db), nie <Link NetSearch>.
    """
    raw = song.get("HasLinks")
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in ("1", "true", "yes")
    return False


def _parse_group_by_filter(filt: str) -> Optional[tuple[str, int]]:
    """group by genre | group by year range N → (kind, step)."""
    text = _normalize_filter_text(filt).lower()
    if not text.startswith("group by"):
        return None
    rest = text[len("group by"):].strip()
    m = re.match(r"year\s+range\s+(\d+)", rest)
    if m:
        return ("year", max(1, int(m.group(1))))
    if rest.startswith("genre"):
        return ("genre", 0)
    if rest.startswith("artist"):
        return ("artist", 0)
    if rest.startswith("album"):
        return ("album", 0)
    if rest.startswith("year"):
        return ("year", 1)
    return None


def _song_bpm(song: dict) -> float:
    raw = (song.get("Tags.Bpm") or "").strip()
    if not raw:
        return 0.0
    try:
        val = float(raw)
        if 0.2 <= val <= 2.0:
            return 60.0 / val
        if 20 <= val <= 300:
            return val
    except ValueError:
        pass
    return 0.0


def _camelot_normalize(key: str) -> str:
    from engine_generator import camelot_normalize

    return camelot_normalize(key)


def _camelot_parts(key: str) -> Optional[tuple[int, str]]:
    ck = _camelot_normalize(key)
    m = re.match(r"(\d+)([AB])", ck or "", re.I)
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def _key_difference(ref_key: str, song_key: str) -> Optional[int]:
    p1 = _camelot_parts(ref_key)
    p2 = _camelot_parts(song_key)
    if not p1 or not p2:
        return None
    n1, l1 = p1
    n2, l2 = p2
    if n1 == n2 and l1 == l2:
        return 0
    if n1 == n2:
        return 1
    return min(abs(n1 - n2), 12 - abs(n1 - n2))


def _parse_deck_relative_limits(filt: str) -> tuple[Optional[float], Optional[int]]:
    text = _normalize_filter_text(filt)
    max_bpm: Optional[float] = None
    max_key: Optional[int] = None
    m = re.search(
        r"(?:bpm\s*difference|bpmdiff)\s*(<=|<|=)\s*(\d+(?:\.\d+)?)",
        text,
        re.I,
    )
    if m:
        max_bpm = float(m.group(2))
    m = re.search(
        r"(?:key\s*difference|keydiff)\s*(<=|<|=)\s*(\d+)",
        text,
        re.I,
    )
    if m:
        max_key = int(m.group(2))
    return max_bpm, max_key


def _strip_deck_relative_conditions(filt: str) -> str:
    text = _normalize_filter_text(filt)
    text = re.sub(
        r"(?:\s*(?:and|or)\s*)?"
        r"(?:bpm\s*difference|bpmdiff|key\s*difference|keydiff|pitch\s*difference)"
        r"\s*(?:<=|>=|<|>|=)\s*\d+(?:\.\d+)?",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s*(?:and|or)\s*$", "", text.strip(), flags=re.I)
    text = re.sub(r"^(?:and|or)\s+", "", text.strip(), flags=re.I)
    return text.strip()


def _pick_deck_reference_song(
    songs: List[dict],
    valid_paths: Set[str],
    deck_reference_path: Optional[str] = None,
) -> Optional[dict]:
    if deck_reference_path:
        target = normalize_path(deck_reference_path)
        for s in songs:
            if normalize_path(s.get("FilePath", "") or "") == target:
                return s

    best: Optional[dict] = None
    best_lp = -1
    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if not path or normalize_path(path) not in valid_paths:
            continue
        try:
            lp = int(float(s.get("Infos.LastPlay") or 0))
        except (TypeError, ValueError):
            lp = 0
        if lp >= best_lp and _song_bpm(s) > 0 and (s.get("Tags.Key") or "").strip():
            best_lp = lp
            best = s
    if best:
        return best

    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if path and normalize_path(path) in valid_paths and _song_bpm(s) > 0:
            return s
    return None


def _expand_deck_relative_filter(
    filter_text: str,
    songs: List[dict],
    valid_paths: Set[str],
    path_to_norm: Dict[str, str],
    deck_reference_path: Optional[str] = None,
) -> List[str]:
    ref = _pick_deck_reference_song(songs, valid_paths, deck_reference_path)
    if not ref:
        return []
    max_bpm, max_key = _parse_deck_relative_limits(filter_text)
    if max_bpm is None and max_key is None:
        return []
    ref_bpm = _song_bpm(ref)
    ref_key = (ref.get("Tags.Key") or "").strip()
    ref_np = normalize_path(ref.get("FilePath", "") or "")
    static_filter = _strip_deck_relative_conditions(filter_text)

    paths: List[str] = []
    seen: set[str] = set()
    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if not path:
            continue
        np = normalize_path(path)
        if np not in valid_paths:
            continue
        if static_filter and not _song_matches_filter(static_filter, s):
            continue
        if max_bpm is not None:
            bpm = _song_bpm(s)
            if bpm <= 0 or abs(bpm - ref_bpm) > max_bpm:
                continue
        if max_key is not None:
            kd = _key_difference(ref_key, (s.get("Tags.Key") or "").strip())
            if kd is None or kd > max_key:
                continue
        p = path_to_norm.get(np, path)
        if p and p not in seen:
            seen.add(p)
            paths.append(p)
    return paths


def _group_label_for_song(kind: str, step: int, song: dict) -> str:
    if kind == "genre":
        from vdj_parser import parse_tags_value

        tags = parse_tags_value(song.get("Tags.Genre", ""))
        if tags:
            return tags[0].lstrip("#").strip() or "(No Genre)"
        return "(No Genre)"
    if kind == "artist":
        return (song.get("Tags.Artist") or song.get("Tags.Author") or "").strip() or "(No Artist)"
    if kind == "album":
        return (song.get("Tags.Album") or "").strip() or "(No Album)"
    if kind == "year":
        try:
            year = int(float(song.get("Tags.Year") or 0))
        except (TypeError, ValueError):
            year = 0
        if year <= 0:
            return "(No Year)"
        if step <= 1:
            return str(year)
        start = (year // step) * step
        return f"{start}-{start + step - 1}"
    return "(Other)"


def _expand_group_by_to_playlists(
    filter_text: str,
    songs: List[dict],
    valid_paths: Set[str],
    path_to_norm: Dict[str, str],
) -> List["Playlist"]:
    from unified_model import Playlist

    spec = _parse_group_by_filter(filter_text)
    if not spec:
        return []
    kind, step = spec
    groups: Dict[str, List[str]] = {}
    seen_in_group: Dict[str, set[str]] = {}

    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if not path:
            continue
        np = normalize_path(path)
        if np not in valid_paths:
            continue
        label = _group_label_for_song(kind, step, s)
        p = path_to_norm.get(np, path)
        if not p:
            continue
        groups.setdefault(label, [])
        seen_in_group.setdefault(label, set())
        if p not in seen_in_group[label]:
            seen_in_group[label].add(p)
            groups[label].append(p)

    out: List[Playlist] = []
    for label in sorted(groups.keys(), key=lambda x: x.lower()):
        paths = groups[label]
        if paths:
            out.append(Playlist(name=label, track_ids=paths, is_folder=False))
    return out


def _song_rating(song: dict) -> float:
    try:
        return float(song.get("Tags.Stars") or 0)
    except (TypeError, ValueError):
        return 0.0


def _song_play_count(song: dict) -> int:
    try:
        return int(float(song.get("Infos.PlayCount") or 0))
    except (TypeError, ValueError):
        return 0


def _song_length(song: dict) -> float:
    try:
        return float(song.get("Infos.SongLength") or 0)
    except (TypeError, ValueError):
        return 0.0


def _days_since_first_seen(song: dict) -> Optional[float]:
    try:
        fs = int(float(song.get("Infos.FirstSeen") or 0))
        if fs <= 0:
            return None
        return (time.time() - fs) / 86400.0
    except (TypeError, ValueError):
        return None


def _field_text(song: dict, field: str) -> str:
    if field in ("artist", "author"):
        return (song.get("Tags.Artist") or song.get("Tags.Author") or "").lower()
    if field == "title":
        return (song.get("Tags.Title") or "").lower()
    if field == "album":
        return (song.get("Tags.Album") or "").lower()
    if field == "genre":
        return (song.get("Tags.Genre") or "").lower()
    if field in ("user1", "user 1"):
        return (song.get("Tags.User1") or "").lower()
    if field in ("user2", "user 2"):
        return (song.get("Tags.User2") or "").lower()
    if field == "filename":
        fp = (song.get("FilePath") or "").replace("\\", "/")
        return fp.rsplit("/", 1)[-1].lower()
    if field == "filepath":
        return (song.get("FilePath") or "").lower()
    return ""


def _tag_field_keys(song: dict, field: str) -> set[str]:
    from vdj_parser import parse_tags_value

    key_map = {
        "user1": "Tags.User1",
        "user 1": "Tags.User1",
        "user2": "Tags.User2",
        "user 2": "Tags.User2",
        "genre": "Tags.Genre",
    }
    fkey = key_map.get(field.lower(), "Tags.Genre")
    return {_normalize_tag_key(t) for t in parse_tags_value(song.get(fkey, ""))}


def _normalize_tag_key(tag: str) -> str:
    t = (tag or "").strip().lstrip("#").lower()
    return re.sub(r"[\s_\-]+", "", t)


def _extract_has_tag_from_condition(cond: str) -> Optional[str]:
    cond = (cond or "").strip()
    for pat in (
        r'(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+"([^"]+)"',
        r"(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+'([^']+)'",
        r"(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+(\S+)",
    ):
        m = re.search(pat, cond, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _eval_filter_condition(cond: str, song: dict) -> bool:
    """Sprawdza pojedynczy warunek filtra VDJ."""
    from vdj_parser import parse_tags_value

    raw_cond = _normalize_filter_text(cond)
    if not raw_cond:
        return True
    cond = raw_cond.lower()

    if re.fullmatch(r"duplicates", cond):
        return True

    if re.search(r"\bexists?\s*=\s*1\b", cond):
        return bool((song.get("FilePath") or "").strip())

    m = re.search(r"\bhas\s+links\s*=\s*([01])\b", cond, re.I)
    if m:
        want = m.group(1) == "1"
        has = _song_has_links(song)
        return has if want else (not has)

    if "drive is" in cond and ('""' in cond or "''" in cond):
        fp = (song.get("FilePath") or "").strip()
        return bool(fp) and not fp.lower().startswith("netsearch:")

    m = re.search(r"days since first seen\s*(<=|>=|<|>)\s*(\d+)", cond, re.I)
    if m:
        days = _days_since_first_seen(song)
        if days is None:
            return False
        op, val = m.group(1), int(m.group(2))
        if op == "<=":
            return days <= val
        if op == ">=":
            return days >= val
        if op == "<":
            return days < val
        return days > val

    m = re.search(r"play count\s*(>=|<=|>|<|=)\s*(\d+)", cond, re.I)
    if m:
        pc = _song_play_count(song)
        op, val = m.group(1), int(m.group(2))
        if op == ">=":
            return pc >= val
        if op == "<=":
            return pc <= val
        if op == ">":
            return pc > val
        if op == "<":
            return pc < val
        return pc == val

    m = re.search(r"rating\s*(>=|<=|>|<|=)\s*(\d+)", cond, re.I)
    if m:
        rating = _song_rating(song)
        op, val = m.group(1), int(m.group(2))
        if op == ">=":
            return rating >= val
        if op == "<=":
            return rating <= val
        if op == ">":
            return rating > val
        if op == "<":
            return rating < val
        return rating == val

    m = re.search(r"length\s*(>=|<=|>|<)\s*(\d+(?:\.\d+)?)", cond, re.I)
    if m:
        length = _song_length(song)
        op, val = m.group(1), float(m.group(2))
        if op == ">=":
            return length >= val
        if op == "<=":
            return length <= val
        if op == ">":
            return length > val
        return length < val

    for field in ("user 2", "user 1", "genre"):
        m = re.search(
            rf"{field}\s+is\s+[\"']?#?([^\"']+)[\"']?",
            raw_cond,
            re.I,
        )
        if m:
            tag = _normalize_tag_key(m.group(1))
            return tag in _tag_field_keys(song, field)

    if "has tag" in cond:
        tag_raw = _extract_has_tag_from_condition(raw_cond)
        if tag_raw is not None:
            tag = _normalize_tag_key(tag_raw)

            def tag_keys(field: str) -> set[str]:
                return {_normalize_tag_key(t) for t in parse_tags_value(song.get(field, ""))}

            if "user 1" in cond or "user1" in cond.replace(" ", ""):
                return tag in tag_keys("Tags.User1")
            if "user 2" in cond or "user2" in cond.replace(" ", ""):
                return tag in tag_keys("Tags.User2")
            if "genre" in cond:
                return tag in tag_keys("Tags.Genre")

    for field in ("user 1", "user 2", "genre", "title", "artist", "album", "filename", "filepath"):
        neg = "doesn't contain" in cond or "does not contain" in cond
        m = re.search(
            rf"{re.escape(field)}\s+(?:doesn't contain|does not contain|contains)\s+[\"']?([^\"']+)[\"']?",
            raw_cond,
            re.I,
        )
        if m:
            val = m.group(1).strip().lstrip("#").lower()
            hay = _field_text(song, field)
            return (val not in hay) if neg else (val in hay)

    if "genre is" in cond or "genre=" in cond:
        m = re.search(r"genre\s+(?:is|=)\s*[\"']?#?([^\"'\s]+)", raw_cond, re.I)
        if m:
            tag = m.group(1).strip().lstrip("#").lower()
            tags = {t.lstrip("#").lower() for t in parse_tags_value(song.get("Tags.Genre", ""))}
            return tag in tags

    m = re.search(r"type\s+is\s+not\s+(\w+)", cond, re.I)
    if m:
        kind = m.group(1).lower()
        fp = (song.get("FilePath") or "").lower()
        if kind == "karaoke":
            return ".cdg" not in fp and "karaoke" not in fp
        if kind == "video":
            return not any(fp.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi"))
        if kind == "audio":
            return True
        return True

    m = re.search(r"type\s*=\s*(\w+)", cond, re.I)
    if m:
        kind = m.group(1).lower()
        fp = (song.get("FilePath") or "").lower()
        if kind == "audio":
            return not any(fp.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi", ".cdg"))
        if kind == "video":
            return any(fp.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi"))
        if kind == "karaoke":
            return ".cdg" in fp or "karaoke" in fp

    return False


def song_matches_filter(filter_text: str, song: dict) -> bool:
    """Sprawdza czy utwór pasuje do filtra VDJ (or/and)."""
    return _song_matches_filter(filter_text, song)


def _song_matches_filter(filter_text: str, song: dict) -> bool:
    if not filter_text or not filter_text.strip():
        return False
    text = _normalize_filter_text(filter_text)
    parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    for part in parts:
        and_parts = re.split(r"\s+and\s+", part.strip(), flags=re.IGNORECASE)
        if all(_eval_filter_condition(ap, song) for ap in and_parts if ap.strip()):
            return True
    return False


def _expand_duplicates(
    songs: List[dict],
    valid_paths: Set[str],
    path_to_norm: Dict[str, str],
) -> List[str]:
    by_hash: Dict[str, List[str]] = {}
    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if not path:
            continue
        np = normalize_path(path)
        if np not in valid_paths:
            continue
        h = (s.get("Infos.FileHash") or np).strip()
        by_hash.setdefault(h, []).append(path_to_norm.get(np, path))
    out: List[str] = []
    seen: set[str] = set()
    for paths in by_hash.values():
        if len(paths) < 2:
            continue
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _expand_filter_to_paths(
    filter_text: str,
    songs: List[dict],
    valid_paths: Set[str],
    path_to_norm: Dict[str, str],
    *,
    deck_reference_path: Optional[str] = None,
) -> List[str]:
    filt = _normalize_filter_text(filter_text)
    if not filt or _is_unexportable_filter(filt):
        return []
    if _is_group_by_filter(filt):
        return []
    if _is_deck_relative_filter(filt):
        return _expand_deck_relative_filter(
            filt, songs, valid_paths, path_to_norm, deck_reference_path
        )
    if filt.lower() == "duplicates":
        return _expand_duplicates(songs, valid_paths, path_to_norm)

    top_m = re.match(
        r"top\s+(\d+)\s+(lastplay|last play|nbplay|play count|first seen|first\s*seen)\s*(.*)$",
        filt,
        re.I,
    )
    remainder = filt
    top_n: Optional[int] = None
    sort_key = ""
    if top_m:
        top_n = int(top_m.group(1))
        sort_key = top_m.group(2).lower().replace(" ", "")
        remainder = (top_m.group(3) or "").strip()
        if remainder.lower().startswith("and "):
            remainder = remainder[4:].strip()

    matched: List[dict] = []
    match_text = remainder if top_n else filt
    for s in songs:
        path = (s.get("FilePath") or "").strip()
        if not path:
            continue
        np = normalize_path(path)
        if np not in valid_paths:
            continue
        if top_n and not match_text:
            matched.append(s)
        elif _song_matches_filter(match_text, s):
            matched.append(s)

    if top_n:
        if "lastplay" in sort_key:
            matched.sort(
                key=lambda s: int(float(s.get("Infos.LastPlay") or 0)),
                reverse=True,
            )
        elif "firstseen" in sort_key:
            matched.sort(
                key=lambda s: int(float(s.get("Infos.FirstSeen") or 0)),
                reverse=True,
            )
        else:
            matched.sort(key=_song_play_count, reverse=True)
        matched = matched[:top_n]

    paths: List[str] = []
    seen: set[str] = set()
    for s in matched:
        np = normalize_path(s.get("FilePath", "") or "")
        p = path_to_norm.get(np, s.get("FilePath", "") or "")
        if p and p not in seen:
            seen.add(p)
            paths.append(p)
    return paths


def _is_excluded_from_serato_transfer(rel_path: str) -> bool:
    """
    Listy których nie przenosimy do Serato:
    - My Library (i literówka „My Libery”)
    - Compatible* (Compatible songs, Compatible Damsza, …)
    """
    if not rel_path:
        return False
    p = rel_path.replace("\\", "/").lower()
    if "my library" in p or "my libery" in p:
        return True
    leaf = p.rsplit("/", 1)[-1]
    if leaf.endswith(".vdjfolder"):
        leaf = leaf[: -len(".vdjfolder")]
    if leaf == "compatible" or leaf.startswith("compatible "):
        return True
    for seg in p.split("/"):
        name = seg
        if name.endswith(".vdjfolder"):
            name = name[: -len(".vdjfolder")]
        if name.endswith(".subfolders"):
            name = name[: -len(".subfolders")]
        if name == "compatible" or name.startswith("compatible "):
            return True
    return False


def _is_my_library_path(rel_path: str) -> bool:
    """Alias wsteczny — wykluczenia transferu Serato (My Library + Compatible)."""
    return _is_excluded_from_serato_transfer(rel_path)


def is_grow_serato_crate(
    *,
    name: str = "",
    stem: str = "",
    filter_text: str = "",
) -> bool:
    """
    Crate rosnący przy każdym imporcie (scalanie lokalnych ścieżek).
    LINKI / filtr „Has Links = 1”. Streaming z listy VDJ jest zachowywany
    (jak na innych listach mieszanych) — osobno w Library SQLite.
    """
    leaf = (name or "").strip().lower()
    if not leaf and stem:
        leaf = stem.replace("\\", "/").split("%%")[-1].strip().lower()
    if leaf == "linki":
        return True
    ft = _normalize_filter_text(filter_text).lower()
    return bool(re.search(r"\bhas\s+links\s*=\s*1\b", ft))


def _extract_vdjfolder_filter(content: str) -> str:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return ""
    filt = root.get("filter") or root.get("Filter") or ""
    if not filt and root.tag == "FilterFolder":
        child = root.find("VirtualFolder") or root.find("folder")
        if child is not None:
            filt = child.get("filter") or child.get("Filter") or ""
    return (filt or "").strip()


def _exportable_playlist_entry_path(path: str, song_elem=None) -> Optional[str]:
    """
    Ścieżka z wpisu VirtualFolder (.vdjfolder) nadająca się do eksportu Serato/RB,
    nawet gdy utwór nie ma rekordu w database.xml (typowe dla Tidal online w playlistach).
    """
    from serato_offline import is_vdj_cache_path
    from vdj_streaming import extract_tidal_id, is_tidal_path

    p = (path or "").strip()
    if not p:
        return None
    if is_tidal_path(p):
        return p
    if is_vdj_cache_path(p):
        ns = ""
        if song_elem is not None:
            ns = (song_elem.get("netsearchId") or song_elem.get("netsearchid") or "").strip()
        tid = extract_tidal_id(ns) or extract_tidal_id(p)
        if tid:
            return f"netsearch://td{tid}"
        return p
    return None


def _playlist_paths_from_vdjfolder_content(
    content: str,
    songs: List[dict],
    valid_paths: Set[str],
    path_to_norm: Dict[str, str],
    *,
    vdjfolders: Optional[Dict[str, str]] = None,
    deck_reference_path: Optional[str] = None,
) -> tuple[List[str], bool, str]:
    """
    Parsuje vdjfolder → (ścieżki utworów, is_filter_list, filter_text).
    Filter listy są rozwijane do aktualnej listy ścieżek z bazy.
    """
    content = _resolve_vdjfolder_content(content, vdjfolders)
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return [], False, ""

    if root.tag == "FavoriteFolder":
        return [], False, ""

    filt = _extract_vdjfolder_filter(content)

    if filt:
        if _is_unexportable_filter(filt):
            return [], True, filt
        if _is_group_by_filter(filt):
            return [], True, filt
        paths = _expand_filter_to_paths(
            filt,
            songs,
            valid_paths,
            path_to_norm,
            deck_reference_path=deck_reference_path,
        )
        return paths, True, filt

    if root.tag not in ("VirtualFolder", "FilterFolder"):
        return [], False, ""

    paths = []
    for song_elem in root.findall("song"):
        p = (song_elem.get("path") or "").strip()
        if not p:
            continue
        np = normalize_path(p)
        if np in valid_paths:
            paths.append(path_to_norm.get(np, p))
            continue
        export_p = _exportable_playlist_entry_path(p, song_elem)
        if export_p:
            paths.append(export_p)
    return paths, False, ""


def _vdjfolder_path_parts(rel_path: str) -> tuple[str, ...]:
    """MyLists/foo.subfolders/bar.vdjfolder → ('MyLists', 'foo', 'bar')."""
    norm = rel_path.replace("\\", "/")
    if not norm.lower().endswith(".vdjfolder"):
        return ()
    stem = norm[: -len(".vdjfolder")]
    parts: list[str] = []
    for seg in stem.split("/"):
        if not seg:
            continue
        if seg.endswith(".subfolders"):
            seg = seg[: -len(".subfolders")]
        parts.append(seg)
    return tuple(parts)


def _parse_subfolder_order_files(extra_files: Optional[Dict[str, bytes]]) -> Dict[str, List[str]]:
    """Mapuje 'MyLists/gatunki' → kolejność nazw podfolderów."""
    orders: Dict[str, List[str]] = {}
    if not extra_files:
        return orders
    for rel_path, raw in extra_files.items():
        p = rel_path.replace("\\", "/")
        if not p.endswith(".subfolders/order"):
            continue
        parent = p[: -len(".subfolders/order")]
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        names = [line.strip() for line in text.splitlines() if line.strip()]
        if names:
            orders[parent] = names
    return orders


def _sort_child_names(names: Set[str], order: Optional[List[str]]) -> List[str]:
    if not order:
        return sorted(names, key=lambda n: n.lower())
    rank = {name.lower(): i for i, name in enumerate(order)}

    def sort_key(name: str) -> tuple:
        return (rank.get(name.lower(), 10_000), name.lower())

    return sorted(names, key=sort_key)


def vdjfolders_to_playlist_tree(
    vdjfolders: Dict[str, str],
    songs: List[dict],
    valid_paths: Set[str],
    extra_files: Optional[Dict[str, bytes]] = None,
    *,
    keep_empty_folders: bool = True,
    resolve_vdjfolders: Optional[Dict[str, str]] = None,
    deck_reference_path: Optional[str] = None,
) -> List["Playlist"]:
    """
    Buduje drzewo playlist z ścieżek plików .vdjfolder (np. MyLists/gatunki/disco.vdjfolder).
    Kolejność rodzeństwa z plików *.subfolders/order w backupie VDJ.
    Filter listy VDJ są zawsze rozwijane do snapshotu ścieżek (zwykłe playlisty).

    keep_empty_folders: True = zachowaj puste foldery (drzewo 1:1 z VDJ).
    """
    from unified_model import Playlist

    path_to_norm = {
        normalize_path(s.get("FilePath", "") or ""): s.get("FilePath", "") or ""
        for s in songs
    }
    path_to_norm = {k: v for k, v in path_to_norm.items() if k and v}
    orders = _parse_subfolder_order_files(extra_files)
    resolve_map = resolve_vdjfolders if resolve_vdjfolders is not None else vdjfolders

    # parts tuple → Playlist (leaf lub folder)
    nodes: Dict[tuple, Playlist] = {}
    child_names: Dict[tuple, Set[str]] = {}

    for rel_path, content in vdjfolders.items():
        if _is_vdj_filter_tree_path(rel_path):
            resolved = _resolve_vdjfolder_content(content, resolve_map)
            filt_probe = _extract_vdjfolder_filter(resolved)
            norm_low = rel_path.replace("\\", "/").strip("/").lower()
            if not (
                norm_low.startswith("folders/filters/")
                and _is_group_by_filter(filt_probe or "")
            ):
                continue
        if _is_my_library_path(rel_path):
            continue
        norm = rel_path.replace("\\", "/")
        if not norm.lower().endswith(".vdjfolder"):
            continue
        parts = _vdjfolder_path_parts(norm)
        if not parts:
            continue

        name = parts[-1]
        paths, is_filter, filt = _playlist_paths_from_vdjfolder_content(
            content,
            songs,
            valid_paths,
            path_to_norm,
            vdjfolders=resolve_map,
            deck_reference_path=deck_reference_path,
        )

        if is_filter and filt and _is_unexportable_filter(filt):
            continue

        if is_filter and filt and _is_group_by_filter(filt):
            children = _expand_group_by_to_playlists(
                filt, songs, valid_paths, path_to_norm
            )
            if children:
                nodes[parts] = Playlist(name=name, track_ids=[], is_folder=True)
                for child in children:
                    child_parts = parts + (child.name,)
                    nodes[child_parts] = child
                    child_names.setdefault(parts, set()).add(child.name)
            elif keep_empty_folders:
                nodes[parts] = Playlist(name=name, track_ids=[], is_folder=True)
            for i in range(len(parts)):
                parent = parts[:i]
                child_names.setdefault(parent, set()).add(parts[i])
                if i > 0 and parent not in nodes:
                    nodes[parent] = Playlist(name=parent[-1], track_ids=[], is_folder=True)
            continue

        if is_filter and filt and not paths:
            if keep_empty_folders:
                nodes[parts] = Playlist(
                    name=name, track_ids=[], is_folder=True, filter_text=filt or ""
                )
            else:
                continue
        elif paths:
            # Snapshot filtra → zwykła playlista; wyjątek: Has Links zostaje smartlistą
            keep_filter = is_filter and filt and filt.strip().lower().startswith("has links")
            nodes[parts] = Playlist(
                name=name,
                track_ids=paths,
                is_folder=False,
                filter_text=filt if keep_filter else "",
            )
        elif not keep_empty_folders:
            continue
        else:
            nodes[parts] = Playlist(
                name=name,
                track_ids=[],
                is_folder=True,
                filter_text=filt if is_filter else "",
            )

        for i in range(len(parts)):
            parent = parts[:i]
            child_names.setdefault(parent, set()).add(parts[i])
            if i > 0 and parent not in nodes:
                nodes[parent] = Playlist(name=parent[-1], track_ids=[], is_folder=True)

    def build_level(parent: tuple) -> List[Playlist]:
        names = child_names.get(parent, set())
        if not names:
            return []
        ordered = _sort_child_names(names, orders.get("/".join(parent)))
        out: List[Playlist] = []
        for child_name in ordered:
            child_parts = parent + (child_name,)
            node = nodes.get(child_parts)
            if not node:
                continue
            sub = build_level(child_parts)
            if sub:
                node = Playlist(
                    name=node.name,
                    track_ids=list(node.track_ids),
                    is_folder=True,
                    children=sub,
                )
            elif (
                not keep_empty_folders
                and node.is_folder
                and not node.track_ids
            ):
                continue
            out.append(node)
        return out

    return build_level(())


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
        paths, _is_filter, _filt = _playlist_paths_from_vdjfolder_content(
            content, songs, valid_paths, path_to_norm, vdjfolders=vdjfolders
        )
        if paths:
            playlists.append(Playlist(name=name, track_ids=paths, is_folder=False))
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
                if not p:
                    continue
                np = normalize_path(p)
                if np and np in valid_paths:
                    paths.append(path_to_norm.get(np, p))
                    continue
                export_p = _exportable_playlist_entry_path(p, song)
                if export_p:
                    paths.append(export_p)
            if paths:
                playlists.append(Playlist(name=name, track_ids=paths, is_folder=False))
        except ET.ParseError:
            continue
    return playlists
