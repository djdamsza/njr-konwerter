"""
Parser bazy danych VirtualDJ (database.xml).
Obsługuje odczyt, modyfikację i zapis z zachowaniem formatu.
"""
import copy
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Union
import re

from vdjfolder import normalize_path


# Wzorce koniunkcji – nie dzielić na osobne tagi (np. "Drum n Bass" → jeden tag, nie ["Drum","n","Bass"])
_CONJUNCTION_PATTERNS = frozenset({'n', "n'", "'n'", "'n", '&'})


def _song_keep_score(s: dict) -> int:
    """Wyższy = lepszy kandydat przy scalaniu bliźniaków ścieżki (/Users vs //Users)."""
    score = 0
    fp = str(s.get("FilePath") or "")
    # Preferuj ścieżkę bez wiodącego // (przed normalizacją)
    if fp.startswith("//") and not fp.startswith("///"):
        score -= 100
    for key in (
        "Tags.Title",
        "Tags.Author",
        "Tags.Artist",
        "Tags.Album",
        "Tags.Bpm",
        "Tags.Key",
        "Tags.Genre",
        "Tags.User1",
        "Tags.User2",
        "Tags.Stars",
        "Infos.SongLength",
        "Infos.PlayCount",
        "FileSize",
    ):
        if str(s.get(key) or "").strip():
            score += 1
    score += len(s.get("_children_xml") or [])
    return score


def prepare_songs_for_vdj_write(songs: list[dict]) -> list[dict]:
    """
    Przygotowuje utwory do zapisu database.xml:
    - zawala FilePath // → / (z zachowaniem netsearch://)
    - scala bliźniaki o tej samej ścieżce kanonicznej (zostawia bogatszy wpis)
    """
    prepared: list[dict] = []
    by_norm: dict[str, int] = {}
    for raw in songs:
        s = copy.copy(raw)
        fp = str(s.get("FilePath") or "").strip()
        if fp:
            s["FilePath"] = normalize_path(fp)
        np = str(s.get("FilePath") or "")
        if not np:
            prepared.append(s)
            continue
        if np in by_norm:
            i = by_norm[np]
            if _song_keep_score(s) > _song_keep_score(prepared[i]):
                prepared[i] = s
        else:
            by_norm[np] = len(prepared)
            prepared.append(s)
    return prepared


def _write_vdj_xml_bytes(root: ET.Element) -> bytes:
    """Serializacja jak VDJ na macOS: UTF-8 + CRLF (LF-only VDJ oznacza jako corrupted)."""
    tree = ET.ElementTree(root)
    ET.indent(tree, space=" ", level=0)
    buf = io.BytesIO()
    tree.write(
        buf,
        encoding="utf-8",
        xml_declaration=True,
        default_namespace="",
        method="xml",
    )
    data = buf.getvalue()
    # Ujednolić do CRLF (nie podwajać istniejących \\r\\n)
    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def _merge_conjunction_tokens(tokens: list[str]) -> list[str]:
    """Scala tokeny typu X n Y, X & Y w jeden tag (Drum n Bass, R & B)."""
    result = []
    i = 0
    while i < len(tokens):
        if i + 2 < len(tokens) and tokens[i + 1] in _CONJUNCTION_PATTERNS:
            merged = f"{tokens[i]} {tokens[i + 1]} {tokens[i + 2]}"
            result.append(merged)
            i += 3
        else:
            result.append(tokens[i])
            i += 1
    return result


def parse_tags_value(val: Optional[str]) -> list[str]:
    """Rozbija wartość User1/User2/Genre na listę tagów (np. '#Lata20 #PARTY' -> ['#Lata20', '#PARTY']).
    Scalane są wzorce typu Drum n Bass, R & B – aby uniknąć błędnego tagu 'n'."""
    if not val or not val.strip():
        return []
    tokens = [t.strip() for t in re.split(r'\s+', val.strip()) if t.strip()]
    return _merge_conjunction_tokens(tokens)


def join_tags(tags: list[str]) -> str:
    """Łączy listę tagów w wartość atrybutu (z zachowaniem spacji)."""
    return ' '.join(t.strip() for t in tags if t.strip())


def song_to_dict(elem: ET.Element) -> dict:
    """Konwertuje element <Song> na słownik."""
    d = {
        'FilePath': elem.get('FilePath', ''),
        'FileSize': elem.get('FileSize', ''),
        'Flag': elem.get('Flag', ''),
    }
    tags = elem.find('Tags')
    if tags is not None:
        for k, v in tags.attrib.items():
            d[f'Tags.{k}'] = v or ''
    infos = elem.find('Infos')
    if infos is not None:
        for k, v in infos.attrib.items():
            d[f'Infos.{k}'] = v or ''
    # Zachowaj raw XML dla pozostałych elementów (Poi, Comment, Link, Scan, CustomMix itd.).
    # <Link NetSearch=…> = powiązanie ze streamingiem — NIE to samo co filtr „Has Links”
    # (Linked Tracks są w extra.db). HasLinks ustawiane później przez vdj_linked_tracks.
    children_xml = []
    has_netsearch_link = False
    link_netsearch = ""
    for child in elem:
        if child.tag not in ('Tags', 'Infos'):
            children_xml.append(ET.tostring(child, encoding='unicode'))
            if child.tag == "Link":
                ns = (
                    child.get("NetSearch")
                    or child.get("netsearch")
                    or ""
                ).strip()
                if ns:
                    has_netsearch_link = True
                    if not link_netsearch:
                        link_netsearch = ns
    d['_children_xml'] = children_xml
    d["HasNetSearchLink"] = "1" if has_netsearch_link else "0"
    if link_netsearch:
        d["Link.NetSearch"] = link_netsearch
    return d


def dict_to_song(d: dict, ns: dict) -> ET.Element:
    """Tworzy element <Song> z słownika."""
    attrib = {}
    if d.get('FilePath'):
        # Zawsze kanoniczna ścieżka – VDJ traktuje /Users i //Users jako dwa utwory
        attrib['FilePath'] = normalize_path(str(d['FilePath']))
    if d.get('FileSize'):
        attrib['FileSize'] = str(d['FileSize'])
    if d.get('Flag'):
        attrib['Flag'] = str(d['Flag'])
    song = ET.Element('Song', attrib)
    tag_attrib = {}
    info_attrib = {}
    TAGS_PREFIX = 'Tags.'
    INFOS_PREFIX = 'Infos.'
    for k, v in d.items():
        if k.startswith(TAGS_PREFIX):
            tag_attrib[k[len(TAGS_PREFIX):]] = str(v) if v is not None else ''
        elif k.startswith(INFOS_PREFIX):
            info_attrib[k[len(INFOS_PREFIX):]] = str(v) if v is not None else ''
        elif k.startswith('_'):
            continue
    if tag_attrib:
        tags_elem = ET.SubElement(song, 'Tags', tag_attrib)
    if info_attrib:
        ET.SubElement(song, 'Infos', info_attrib)
    for xml_str in d.get('_children_xml', []):
        try:
            child = ET.fromstring(xml_str)
            song.append(child)
        except ET.ParseError:
            pass
    return song


_ATTR_PAIR_RE = re.compile(r'(\w+)=(\"[^\"]*\"|\'[^\']*\')')
_OPEN_TAG_RE = re.compile(
    r'<([A-Za-z][\w.-]*)((?:\s+[\w.:$-]+=(?:"[^"]*"|\'[^\']*\'))*)\s*(/?>)'
)


def _sanitize_vdj_xml_duplicate_attrs(xml_text: str) -> str:
    """VirtualDJ czasem zapisuje powtórzone atrybuty (np. Artist dwa razy) – ET.parse wtedy pada."""
    def fix_tag(m: re.Match) -> str:
        tag_name = m.group(1)
        attrs_str = m.group(2) or ''
        closing = m.group(3)
        seen: dict[str, str] = {}
        order: list[str] = []
        for am in _ATTR_PAIR_RE.finditer(attrs_str):
            key = am.group(1)
            if key not in seen:
                order.append(key)
            seen[key] = am.group(0)
        if not seen:
            return f'<{tag_name}{closing}'
        new_attrs = ' '.join(seen[k] for k in order)
        return f'<{tag_name} {new_attrs}{closing}'

    return _OPEN_TAG_RE.sub(fix_tag, xml_text)


def load_database(path: Union[str, Path]) -> tuple[list[dict], str]:
    """
    Wczytuje database.xml. Zwraca (lista utworów, wersja bazy).
    FilePath jest normalizowany (// → /), żeby porównań/zapis nie mnożyły bliźniaków.
    HasLinks ustawiane z extra.db (Linked Tracks), nie z <Link NetSearch>.
    """
    xml_text = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        root = ET.fromstring(_sanitize_vdj_xml_duplicate_attrs(xml_text))
    version = root.get("Version", "")
    songs = []
    for song_elem in root.findall("Song"):
        d = song_to_dict(song_elem)
        fp = d.get("FilePath") or ""
        if fp:
            d["FilePath"] = normalize_path(fp)
        songs.append(d)
    try:
        from vdj_linked_tracks import apply_linked_tracks_flags

        apply_linked_tracks_flags(songs, Path(path).resolve().parent)
    except Exception:
        pass
    return songs, version


def save_database(path: Union[str, Path, io.BufferedIOBase, io.BytesIO], songs: list[dict], version: str) -> None:
    """
    Zapisuje database.xml w formacie akceptowanym przez VirtualDJ:
    - CRLF
    - FilePath bez //Users (kanonicznie)
    - bez podwójnych wpisów tej samej ścieżki
    """
    prepared = prepare_songs_for_vdj_write(songs)
    root = ET.Element("VirtualDJ_Database", Version=version or "")
    for d in prepared:
        root.append(dict_to_song(d, {}))
    data = _write_vdj_xml_bytes(root)
    if hasattr(path, "write"):
        path.write(data)
        return
    Path(path).write_bytes(data)


def get_all_tags(songs: list[dict], field: str) -> dict[str, int]:
    """Zwraca słownik {tag: liczba_wystąpień} dla User1, User2 lub Genre."""
    prefix = f'Tags.{field}'
    counts = {}
    for s in songs:
        val = s.get(prefix, '')
        for tag in parse_tags_value(val):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def merge_tags_across_fields(
    songs: list[dict],
    selections: list[tuple[str, str]],
    new_tag: str,
    target_field: str,
) -> int:
    """
    Scalanie tagów z różnych pól. selections: [(field, tag), ...]
    Dla każdego utworu z wybranymi tagami: usuwa je z ich pól, dodaje new_tag do target_field.
    """
    modified = 0
    target_prefix = f'Tags.{target_field}'
    sel_set = set((f, t) for f, t in selections)

    for s in songs:
        has_any = False
        for field, old_tag in selections:
            prefix = f'Tags.{field}'
            tags = parse_tags_value(s.get(prefix, ''))
            if old_tag in tags:
                has_any = True
                break
        if not has_any:
            continue

        # Usuń stare tagi
        for field, old_tag in selections:
            prefix = f'Tags.{field}'
            tags = parse_tags_value(s.get(prefix, ''))
            tags = [t for t in tags if t != old_tag]
            s[prefix] = join_tags(tags)

        # Dodaj nowy tag do target
        tags = parse_tags_value(s.get(target_prefix, ''))
        if new_tag not in tags:
            tags.append(new_tag)
            s[target_prefix] = join_tags(tags)
        modified += 1
    return modified


def merge_tags_in_songs(songs: list[dict], field: str, old_tags: list[str], new_tag: str) -> int:
    """
    Zamienia stare tagi na nowy w polu User1/User2/Genre.
    Zwraca liczbę zmodyfikowanych utworów.
    """
    prefix = f'Tags.{field}'
    modified = 0
    for s in songs:
        val = s.get(prefix, '')
        tags = parse_tags_value(val)
        changed = False
        new_tags = []
        for t in tags:
            if t in old_tags:
                if new_tag not in new_tags:
                    new_tags.append(new_tag)
                changed = True
            else:
                new_tags.append(t)
        if changed:
            s[prefix] = join_tags(new_tags)
            modified += 1
    return modified


def remove_tags_in_songs(songs: list[dict], field: str, tags_to_remove: list[str]) -> int:
    """
    Usuwa tagi z utworów (bez usuwania samych utworów).
    Zwraca liczbę zmodyfikowanych utworów.
    """
    prefix = f'Tags.{field}'
    to_remove = set(t.strip() for t in tags_to_remove if t.strip())
    modified = 0
    for s in songs:
        val = s.get(prefix, '')
        tags = parse_tags_value(val)
        new_tags = [t for t in tags if t not in to_remove]
        if len(new_tags) != len(tags):
            s[prefix] = join_tags(new_tags)
            modified += 1
    return modified


def merge_tags_in_songs_by_indices(
    songs: list[dict], indices: set[int], field: str, old_tags: list[str], new_tag: str
) -> int:
    """
    Zamienia stare tagi na nowy w polu User1/User2/Genre – tylko dla utworów o indeksach w indices.
    """
    prefix = f'Tags.{field}'
    modified = 0
    for i, s in enumerate(songs):
        if i not in indices:
            continue
        val = s.get(prefix, '')
        tags = parse_tags_value(val)
        changed = False
        new_tags = []
        for t in tags:
            if t in old_tags:
                if new_tag and new_tag not in new_tags:
                    new_tags.append(new_tag)
                changed = True
            else:
                new_tags.append(t)
        if changed:
            s[prefix] = join_tags(new_tags)
            modified += 1
    return modified


def remove_tags_in_songs_by_indices(
    songs: list[dict], indices: set[int], field: str, tags_to_remove: list[str]
) -> int:
    """
    Usuwa tagi z utworów – tylko dla utworów o indeksach w indices.
    """
    prefix = f'Tags.{field}'
    to_remove = set(t.strip() for t in tags_to_remove if t.strip())
    modified = 0
    for i, s in enumerate(songs):
        if i not in indices:
            continue
        val = s.get(prefix, '')
        tags = parse_tags_value(val)
        new_tags = [t for t in tags if t not in to_remove]
        if len(new_tags) != len(tags):
            s[prefix] = join_tags(new_tags)
            modified += 1
    return modified
