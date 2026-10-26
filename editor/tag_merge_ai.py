"""Propozycje scalenia tagów. Jeden token za listę. Zapis jest osobno, po akceptacji."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher

from vdj_parser import get_all_tags, parse_tags_value

_FIELDS = ("Genre", "User1", "User2")
_ENERGY = {"1", "2", "3", "4", "5"}


def tag_key(tag: str) -> str:
    text = unicodedata.normalize("NFKD", tag or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("#", "")
    return re.sub(r"[^a-z0-9]+", "", text)


def is_protected(tag: str) -> bool:
    key = tag_key(tag)
    return key in _ENERGY or key.startswith("lata")


def inventory(songs: list[dict]) -> list[dict]:
    rows = []
    for field in _FIELDS:
        for tag, count in get_all_tags(songs, field).items():
            rows.append({"field": field, "tag": tag, "count": int(count), "key": tag_key(tag)})
    return rows


def tracks_for_tag(songs: list[dict], field: str, tag: str, limit: int = 5) -> list[str]:
    prefix = f"Tags.{field}"
    found = []
    for song in songs:
        if tag not in parse_tags_value(song.get(prefix, "")):
            continue
        author = str(song.get("Tags.Author") or song.get("Tags.Artist") or "").strip()
        title = str(song.get("Tags.Title") or "").strip()
        label = " — ".join(part for part in (author, title) if part)
        found.append(label or "bez nazwy")
        if len(found) >= limit:
            break
    return found


def annotate_small(songs: list[dict], rows: list[dict]) -> list[dict]:
    """Do tagu z 1–5 utworami dokleja te nagrania. Decyzja ma iść po muzyce, nie po nazwie."""
    out = []
    for row in rows:
        item = dict(row)
        item["tracks"] = tracks_for_tag(songs, row["field"], row["tag"]) if row["count"] <= 5 else []
        out.append(item)
    return out


def review_rows(rows: list[dict]) -> list[dict]:
    """Tagi do pokazania modelowi: rzadkie, ten sam zapis w dwóch bankach i bliskie literówki."""
    by_key: dict[str, list[dict]] = {}
    for row in rows:
        by_key.setdefault(row["key"], []).append(row)
    chosen: dict[tuple[str, str], dict] = {}

    def add(row: dict) -> None:
        chosen[(row["field"], row["tag"])] = row

    for row in rows:
        if row["count"] <= 8:
            add(row)
    for group in by_key.values():
        if len(group) >= 2:
            for row in group:
                add(row)

    small = [key for key, group in by_key.items() if len(key) >= 4 and min(row["count"] for row in group) <= 40]
    big = [key for key, group in by_key.items() if len(key) >= 4 and max(row["count"] for row in group) >= 15]
    pool = list(dict.fromkeys(small + big))
    for i, left in enumerate(pool):
        for right in pool[i + 1 :]:
            if abs(len(left) - len(right)) > 2:
                continue
            if SequenceMatcher(None, left, right).ratio() < 0.8:
                continue
            for row in by_key[left] + by_key[right]:
                add(row)
    return list(chosen.values())


def _source_view(row: dict) -> dict:
    view = {"field": row["field"], "tag": row["tag"], "count": row["count"]}
    tracks = row.get("tracks") or []
    if tracks:
        view["tracks"] = tracks
    return view


def _lookup(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["field"], row["tag"]): row for row in rows}


def _target_row(rows: list[dict], new_tag: str, target_field: str) -> dict | None:
    hits = [row for row in rows if row["tag"] == new_tag and row["field"] in _FIELDS]
    if target_field in _FIELDS:
        hits = [row for row in hits if row["field"] == target_field]
    if not hits:
        return None
    return max(hits, key=lambda row: row["count"])


def validate_proposal(item: dict, rows: list[dict]) -> dict | None:
    if not isinstance(item, dict):
        return None
    why = str(item.get("why") or "").strip()
    if len(why) < 8:
        return None
    lookup = _lookup(rows)
    sources = []
    seen = set()
    for raw in item.get("sources") or []:
        if not isinstance(raw, dict):
            continue
        field = str(raw.get("field") or "").strip()
        tag = str(raw.get("tag") or "").strip()
        row = lookup.get((field, tag))
        if row is None or (field, tag) in seen:
            continue
        seen.add((field, tag))
        sources.append(row)
    if not sources:
        return None
    new_tag = str(item.get("newTag") or "").strip()
    if not new_tag:
        for row in sources:
            if row["count"] > 3 or is_protected(row["tag"]):
                return None
            if any(other["key"] == row["key"] and other["count"] >= 15 for other in rows):
                return None
        return {
            "sources": [_source_view(row) for row in sources],
            "newTag": "",
            "targetField": "",
            "targetCount": 0,
            "why": why,
        }
    target = _target_row(rows, new_tag, str(item.get("targetField") or "").strip())
    if target is None:
        return None
    kept = []
    for row in sources:
        if row["field"] == target["field"] and row["tag"] == target["tag"]:
            continue
        same = row["key"] and row["key"] == target["key"]
        if row["count"] >= 15 or is_protected(row["tag"]):
            if not same:
                return None
        kept.append(row)
    if not kept:
        return None
    return {
        "sources": [_source_view(row) for row in kept],
        "newTag": target["tag"],
        "targetField": target["field"],
        "targetCount": target["count"],
        "why": why,
    }


def parse_merge_answer(answer: str, rows: list[dict], limit: int = 100) -> list[dict]:
    text = (answer or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    seen = set()
    for item in data:
        proposal = validate_proposal(item, rows)
        if proposal is None:
            continue
        key = (
            tuple(sorted((src["field"], src["tag"]) for src in proposal["sources"])),
            proposal["newTag"],
            proposal["targetField"],
        )
        if key in seen:
            continue
        seen.add(key)
        proposal["id"] = len(out)
        out.append(proposal)
        if len(out) >= limit:
            break
    return out


def merge_prompt(rows: list[dict], review: list[dict]) -> str:
    keep = [row for row in rows if row["count"] >= 15]
    keep.sort(key=lambda row: -row["count"])
    keep = keep[:160]
    small = sorted((row for row in review if row["count"] <= 5), key=lambda row: (row["count"], row["tag"]))[:150]
    other = sorted((row for row in review if row["count"] > 5), key=lambda row: (row["count"], row["tag"]))[:80]

    def line(row: dict) -> str:
        text = f'{row["field"]}\t{row["count"]}\t{row["tag"]}'
        tracks = row.get("tracks") or []
        if tracks:
            text += "\t" + " | ".join(tracks)
        return text

    return (
        "Sprzątasz tagi biblioteki DJ. Nie układaj tagów po bankach od nowa. "
        "Banki to Genre, User1 i User2 i zostają. Zostaw duży tag w banku, w którym już jest. "
        "Nie scalaj po wspólnym słowie w nazwie. Euro-Disco to nie #Disco-Polo. Disco to nie #Disco-Polo. "
        "Italodance to nie #House, dopóki utwory na liście nie są house. "
        "Nazwa tagu z pliku często kłamie. Decyduje nagranie, nie słowo w tagu. "
        "Children's na The Rembrandts — I'll Be There for You (Theme from Friends) to nie #dziecianimacja. "
        "Friends to serial dla dorosłych, nie bajka. Soundtrack i theme from same nie są tagiem dziecięcym. "
        "Gdy tag ma 1–5 utworów, patrz na wykonawcę i tytuł podane obok. "
        "Wybierz jeden istniejący tag, do którego te nagrania naprawdę należą. "
        "Jak nagrania przeczą nazwie tagu albo nie wskazują jednego tagu, pomiń tę pozycję. Nie zgaduj. "
        "Ten sam tag w dwóch bankach to jedna decyzja: wpisz oba pola w sources, nie rób dwóch kopii opisu. "
        "Literówkę i ten sam tag zapisany drugi raz scalaj. "
        "Tag z 1–3 utworami, który nie jest muzyką i nie pasuje do żadnego dużego tagu, usuń: newTag pusty. "
        "Cel musi już być na liście dużych tagów. Nie wymyślaj nowej nazwy. "
        "Nie łącz energii #1 #2 #3 #4 #5 ani epok #Lata ze sobą. "
        "why po polsku i bez słów Genre, User1, User2: napisz, które nagrania zdecydowały. "
        "Najwyżej 100 pozycji. Najpierw literówki i ten sam tag drugi raz, potem tagi z utworami. "
        "Odpowiedź to sam JSON: "
        '[{"sources":[{"field":"Genre","tag":"dence"}],"newTag":"Dance","targetField":"Genre","why":"literówka Dance"}]. '
        'Usunięcie: {"sources":[{"field":"Genre","tag":"ze"}],"newTag":"","targetField":"","why":"to nie jest utwór"}.\n'
        "Duże tagi, bank, liczba, nazwa. Tu wybierasz cel:\n"
        + "\n".join(line(row) for row in keep)
        + "\nDo sprawdzenia. Przy liczbie 1–5 ostatnia kolumna to utwory:\n"
        + "\n".join(line(row) for row in small + other)
    )
