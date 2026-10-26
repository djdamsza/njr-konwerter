"""Werdykt duplikatów: zielony zostaje, czerwony do usunięcia, reszta bez zaznaczenia.

Ciasne dopasowanie: czas ±1 s, BPM ±0,1, ta sama tonacja Camelot.
Dopisek typu Radio Edit przy jednym tytule to wysokie prawdopodobieństwo, bez kolorów.
"""
from __future__ import annotations

import re

from engine_generator import camelot_normalize

_VERSION = re.compile(
    r"\(([^)]*(?:radio|remix|mix|edit|extended|version|clean|club|original|dub|acoustic|live|instrumental)[^)]*)\)",
    re.I,
)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def bpm_of(value) -> float:
    n = _num(value)
    if n <= 0:
        return 0.0
    if 0.2 <= n <= 2:
        return 60.0 / n
    return n


def _stars(value) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def rank_key(row: dict) -> tuple:
    """Listy, potem gwiazdki, potem uzupełnione dane, potem odtworzenia."""
    lists = int(row.get("playlists_count") or 0)
    stars = _stars(row.get("rating"))
    filled = 0
    if bpm_of(row.get("bpm")) > 0:
        filled += 1
    if (row.get("key") or "").strip():
        filled += 1
    if (row.get("bitrate") or "").strip():
        filled += 1
    if (row.get("genre") or "").strip():
        filled += 1
    try:
        plays = int(float(row.get("playcount") or 0))
    except (TypeError, ValueError):
        plays = 0
    disk = 1 if row.get("pathSource") == "dysk" else 0
    return (lists, stars, filled, min(max(plays, 0), 40), disk)


def why_keep(row: dict) -> str:
    bits = []
    lists = int(row.get("playlists_count") or 0)
    if lists:
        bits.append(f"{lists} list")
    stars = _stars(row.get("rating"))
    if stars:
        bits.append(f"★{stars}")
    try:
        plays = int(float(row.get("playcount") or 0))
    except (TypeError, ValueError):
        plays = 0
    if plays:
        bits.append(f"{plays} odtw.")
    if row.get("pathSource") == "dysk":
        bits.append("plik z dysku")
    return ", ".join(bits) if bits else "słabszy wpis"


def core_title(title: str) -> str:
    text = _VERSION.sub(" ", title or "")
    text = re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", text.lower())
    return " ".join(text.split())


def version_tags(title: str) -> tuple[str, ...]:
    return tuple(sorted(m.group(1).strip().lower() for m in _VERSION.finditer(title or "")))


def keys_match(a: dict, b: dict) -> bool:
    ka = camelot_normalize(str(a.get("key") or ""))
    kb = camelot_normalize(str(b.get("key") or ""))
    return bool(ka and kb and ka == kb)


def tight_pair(a: dict, b: dict) -> bool:
    da, db = _num(a.get("duration")), _num(b.get("duration"))
    if da <= 0 or db <= 0 or abs(da - db) > 1:
        return False
    ba, bb = bpm_of(a.get("bpm")), bpm_of(b.get("bpm"))
    if ba <= 0 or bb <= 0 or abs(ba - bb) > 0.1 + 1e-6:
        return False
    return keys_match(a, b)


def all_tight(rows: list[dict]) -> bool:
    return all(tight_pair(rows[i], rows[j]) for i in range(len(rows)) for j in range(i + 1, len(rows)))


def author_key(author: str) -> str:
    text = re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", (author or "").lower())
    return " ".join(text.split())


def version_buckets(rows: list[dict]) -> list[list[dict]]:
    """Pary z tym samym artystą i tytułem, różniące się dopiskiem (Radio Edit, Remix)."""
    from collections import defaultdict

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        author = author_key(row.get("author") or "")
        core = core_title(row.get("title") or "")
        if len(author) < 2 or len(core) < 6:
            continue
        buckets[(author, core)].append(row)
    found = []
    for items in buckets.values():
        tags = {version_tags(r.get("title") or "") for r in items}
        if len(tags) < 2 or not (2 <= len(items) <= 5):
            continue
        found.append(items)
    found.sort(key=lambda items: ((items[0].get("author") or ""), (items[0].get("title") or "")))
    return found[:80]


def tidal_name_groups(rows: list[dict]) -> list[dict]:
    """Plik i Tidal o tym samym tytule. Ciasne dopasowanie dostaje kolory, reszta zostaje pusta."""
    from collections import defaultdict

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        author = author_key(row.get("author") or "")
        core = core_title(row.get("title") or "")
        if len(author) < 2 or len(core) < 6:
            continue
        buckets[(author, core)].append(row)
    found = []
    for items in buckets.values():
        disks = [r for r in items if r.get("pathSource") == "dysk"]
        streams = [r for r in items if r.get("pathSource") in ("tidal", "cache")]
        if not disks or not streams or len(items) > 5:
            continue
        if all_tight(items):
            verdict = classify_group(items)
            found.append({"group": items, "verdict": verdict})
            continue
        close = []
        for stream in streams:
            for disk in disks:
                da, db = _num(stream.get("duration")), _num(disk.get("duration"))
                ba, bb = bpm_of(stream.get("bpm")), bpm_of(disk.get("bpm"))
                if da > 0 and db > 0 and abs(da - db) <= 1 and ba > 0 and bb > 0 and abs(ba - bb) <= 0.1 + 1e-6:
                    close.append(stream)
                    close.append(disk)
        if not close:
            continue
        uniq = []
        seen = set()
        for row in close:
            path = (row.get("path") or "")
            if path in seen:
                continue
            seen.add(path)
            uniq.append(row)
        note = "Może być ten sam utwór: czas i BPM są w odchyleniu 1 s i 0,1 BPM, ale tonacja się nie zgadza albo jej brak. Nic nie zaznaczam — odsłuchaj Tidal."
        found.append({
            "group": uniq,
            "verdict": {
                "section": "review",
                "label": "wysokie",
                "note": note,
                "rows": [{"path": (r.get("path") or ""), "mark": "", "reason": note} for r in uniq],
            },
        })
    return found[:40]


def high_version(rows: list[dict]) -> bool:
    cores = {core_title(r.get("title") or "") for r in rows}
    cores.discard("")
    if len(cores) != 1:
        return False
    tags = {version_tags(r.get("title") or "") for r in rows}
    return len(tags) > 1


def _path(row: dict) -> str:
    return (row.get("path") or row.get("FilePath") or "").strip()


def classify_group(rows: list[dict]) -> dict:
    ranked = sorted(rows, key=rank_key, reverse=True)
    keep = ranked[0]
    tie = len(ranked) > 1 and rank_key(ranked[0])[:2] == rank_key(ranked[1])[:2]
    disks = [r for r in rows if r.get("pathSource") == "dysk"]
    streams = [r for r in rows if r.get("pathSource") in ("tidal", "cache")]
    version = high_version(rows)
    tight = all_tight(rows)

    def blank(note: str, label: str = "") -> dict:
        return {
            "section": "review",
            "label": label,
            "note": note,
            "rows": [{"path": _path(r), "mark": "", "reason": note} for r in rows],
        }

    if version and not tight:
        tag_note = "Wysokie prawdopodobieństwo: tytuły są blisko, ale dopisek (np. Radio Edit) jest tylko przy jednym. Odsłuchaj, nic nie zaznaczam."
        return blank(tag_note, "wysokie")

    if not tight:
        note = "Ten sam podpis, ale czas, BPM albo tonacja są poza odchyleniem 1 s i 0,1 BPM. Nic nie zaznaczam — sprawdź odsłuch."
        if streams and disks:
            note = "Streaming i plik, ale czas, BPM albo tonacja się nie zgadzają. Nic nie zaznaczam."
        return blank(note)

    if tie and not (len(disks) == 1 and streams):
        return blank("Czas, BPM i tonacja się zgadzają, ale oba są tak samo na listach i gwiazdkach. Nic nie zaznaczam.")

    if len(disks) == 1 and streams:
        chosen = disks[0]
        reason_keep = f"Czas, BPM i tonacja się zgadzają. Zostawiam plik z dysku ({why_keep(chosen)})."
        reason_drop = "Ta sama długość (±1 s), BPM (±0,1) i tonacja co plik z dysku. Do usunięcia z bazy, listy przejdą na plik."
    else:
        chosen = keep
        reason_keep = f"Czas, BPM i tonacja się zgadzają. Zostawiam ważniejszy: {why_keep(chosen)}."
        reason_drop = f"Ten sam czas, BPM i tonacja. Słabszy niż {why_keep(chosen)} — do usunięcia, listy przejdą na zostawiony."

    out_rows = []
    for row in rows:
        mark = "keep" if _path(row) == _path(chosen) else "drop"
        out_rows.append({
            "path": _path(row),
            "mark": mark,
            "reason": reason_keep if mark == "keep" else reason_drop,
        })
    return {
        "section": "proposal",
        "label": "",
        "note": reason_keep,
        "rows": out_rows,
    }


LOW_BITRATE = 128


def _bitrate(row: dict) -> int:
    text = str(row.get("bitrate") or "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 0
    try:
        return int(float(match.group(1)))
    except (TypeError, ValueError):
        return 0


def _plays(row: dict) -> int:
    try:
        return max(0, int(float(row.get("playcount") or 0)))
    except (TypeError, ValueError):
        return 0


def _star_count(row: dict) -> int:
    n = _stars(row.get("rating"))
    if n <= 5:
        return n
    return min(5, int(round(n / 51)))


def _is_disk(row: dict) -> bool:
    return row.get("pathSource") == "dysk"


def _is_stream(row: dict) -> bool:
    return row.get("pathSource") in ("tidal", "cache")


def _low(row: dict) -> bool:
    bitrate = _bitrate(row)
    return bool(bitrate and bitrate < LOW_BITRATE)


def _place(row: dict) -> int:
    """Dysk przed Tidalem, dopóki plik nie ma niskiego bitrate."""
    if _is_disk(row) and not _low(row):
        return 2
    if _is_stream(row):
        return 1
    return 0


def _advice_key(row: dict) -> tuple:
    return (
        _place(row),
        int(row.get("playlists_count") or 0),
        _star_count(row),
        _plays(row),
        _bitrate(row),
    )


def _source_name(row: dict) -> str:
    if _is_disk(row):
        return "plik z dysku"
    if row.get("pathSource") == "cache":
        return "cache"
    return "Tidal"


def _advice_sentence(winner: dict, loser: dict) -> str:
    if _is_disk(winner) and _is_stream(loser) and not _low(winner):
        bitrate = _bitrate(winner)
        quality = f" ({bitrate} kbps)" if bitrate else ""
        return f"Zostawiam plik z dysku{quality}. Tidal przegrywa, dopóki plik nie ma niskiego bitrate."
    if _low(loser) and _is_disk(loser) and _place(winner) > _place(loser):
        return f"Plik z dysku ma {_bitrate(loser)} kbps, więc zostawiam {_source_name(winner)}."
    bits = []
    lists_w = int(winner.get("playlists_count") or 0)
    lists_l = int(loser.get("playlists_count") or 0)
    if lists_w != lists_l:
        bits.append(f"{lists_w} list wobec {lists_l}")
    stars_w, stars_l = _star_count(winner), _star_count(loser)
    if stars_w != stars_l:
        bits.append(f"ocena {'★' * stars_w or 'bez gwiazdek'}")
    plays_w, plays_l = _plays(winner), _plays(loser)
    if plays_w != plays_l:
        bits.append(f"{plays_w} odtworzeń wobec {plays_l}")
    bit_w, bit_l = _bitrate(winner), _bitrate(loser)
    if bit_w != bit_l and (bit_w or bit_l):
        bits.append(f"bitrate {bit_w or '—'} wobec {bit_l or '—'}")
    if not bits:
        return "Zostawiam ten wpis."
    return "Zostawiam ten: " + ", ".join(bits) + "."


def advise_group(rows: list[dict]) -> dict:
    """Wybiera jeden utwór do scalenia. Remis nic nie zaznacza."""
    usable = [row for row in rows or [] if _path(row)]
    if len(usable) < 2:
        return {"keepPath": "", "note": "Za mało utworów do porównania.", "marked": False}
    ranked = sorted(usable, key=_advice_key, reverse=True)
    winner, loser = ranked[0], ranked[1]
    if _advice_key(winner) == _advice_key(loser):
        return {
            "keepPath": "",
            "note": "Remis na bitrate, listach, ocenie i odtworzeniach. Nic nie zaznaczam.",
            "marked": False,
        }
    return {
        "keepPath": _path(winner),
        "note": _advice_sentence(winner, loser),
        "marked": True,
    }
