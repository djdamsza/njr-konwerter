"""Które rekordy wolno pokazać jako duplikat.

Prawdziwy duplikat to plik, który jest na dysku, albo utwór Tidal z identyfikatorem.
netsearch://va…, vj…, dz… nie mają numeru Tidal.
Cache VirtualDJ (.vdjcache) ma numer w Link.NetSearch, nie w nazwie pliku.
Łączy się ze streamem o tym numerze tylko, gdy czas różni się najwyżej o 2 sekundy.
Ten sam tytuł łączy się na tej samej zasadzie.
"""
from __future__ import annotations

from file_analyzer import is_streaming
from vdj_streaming import extract_tidal_id, is_vdj_cache_path

DURATION_SLACK = 2.0


def duplicate_kind(path: str) -> str:
    """'file' | 'tidal' | 'skip'."""
    text = (path or "").strip()
    if not text or is_vdj_cache_path(text):
        return "skip"
    if extract_tidal_id(text):
        return "tidal"
    if is_streaming(text):
        return "skip"
    return "file"


def duration_seconds(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def same_recording(left, right, slack: float = DURATION_SLACK) -> bool:
    a = duration_seconds(left)
    b = duration_seconds(right)
    if a is None or b is None:
        return False
    return abs(a - b) <= slack


def cluster_recordings(rows: list[dict], slack: float = DURATION_SLACK) -> list[list[dict]]:
    """Łączy wiersze o tym samym nagraniu. Jeden wiersz nie tworzy grupy."""
    count = len(rows)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a = find(left)
        b = find(right)
        if a != b:
            parent[a] = b

    for i in range(count):
        tid_i = (rows[i].get("tidal_id") or "").strip()
        for j in range(i + 1, count):
            tid_j = (rows[j].get("tidal_id") or "").strip()
            if tid_i and tid_i == tid_j:
                union(i, j)
                continue
            if same_recording(rows[i].get("duration"), rows[j].get("duration"), slack):
                union(i, j)
    buckets: dict[int, list[dict]] = {}
    for index, row in enumerate(rows):
        buckets.setdefault(find(index), []).append(row)
    return [group for group in buckets.values() if len(group) > 1]


def _song_duration(song: dict):
    return song.get("Infos.SongLength") or song.get("Infos.Duration")


def tidal_duplicate_groups(songs: list[dict]) -> list[list[int]]:
    """Grupy indeksów o tym samym numerze Tidal.

    Cache bez numeru w nazwie bierze Link.NetSearch i wchodzi do grupy tylko,
    gdy czas zgadza się ze streamem. Inaczej link do innej wersji (remix)
    sklejałby dwa różne nagrania.
    """
    from vdj_path_mapping import extract_song_tidal_id

    buckets: dict[str, list[int]] = {}
    for index, song in enumerate(songs or []):
        path = str(song.get("FilePath") or "")
        tid = extract_song_tidal_id(song)
        if not tid:
            continue
        if duplicate_kind(path) == "skip" and not is_vdj_cache_path(path):
            continue
        buckets.setdefault(tid, []).append(index)

    groups: list[list[int]] = []
    for indices in buckets.values():
        if len(indices) < 2:
            continue
        anchored: list[int] = []
        anchored_durations = []
        linked_cache: list[int] = []
        for index in indices:
            path = str(songs[index].get("FilePath") or "")
            if is_vdj_cache_path(path) and not extract_tidal_id(path):
                linked_cache.append(index)
                continue
            anchored.append(index)
            anchored_durations.append(_song_duration(songs[index]))
        for index in linked_cache:
            duration = _song_duration(songs[index])
            if not anchored_durations or any(
                same_recording(duration, other) for other in anchored_durations
            ):
                anchored.append(index)
        if len(anchored) > 1:
            groups.append(anchored)
    return groups
