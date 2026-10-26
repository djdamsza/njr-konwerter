"""Podgląd tagów: lata, gatunek, rodzaj i energia, słownikiem z własnej bazy."""
from __future__ import annotations

import json
import re

_JUNK = {
    "#x", "#użytkowe", "#uzytkowe", "#robertobedros", "#przerwa2.0", "#my_way",
    "#dk", "#nafalii", "#nafali", "#hitynaczasie", "#18stka", "#patorapsy",
}
_ENERGY = {"#1", "#2", "#3", "#4", "#5"}
_LANGUAGE = {
    "polskie": "#Polskie",
    "polish": "#Polskie",
    "francuskie": "#francuskie",
    "french": "#francuskie",
    "niemieckie": "#niemieckie",
    "german": "#niemieckie",
    "deutsch": "#niemieckie",
    "angielskie": "#angielskie",
    "english": "#angielskie",
    "hiszpanskie": "#Latino",
    "hiszpańskie": "#Latino",
    "spanish": "#Latino",
    "brazylijskie": "#Latino",
    "portugalskie": "#Latino",
    "portuguese": "#Latino",
    "latino": "#Latino",
    "latin": "#Latino",
}
_DANCE = {
    "cza-cza": "#cza-cza",
    "czacza": "#cza-cza",
    "cha-cha": "#cza-cza",
    "chacha": "#cza-cza",
    "rumba": "#Rumba",
    "walc": "#walczyk",
    "waltz": "#walczyk",
    "walczyk": "#walczyk",
}
_PINNED = (
    "#Polskie", "#francuskie", "#niemieckie", "#angielskie", "#Latino",
    "#cza-cza", "#Rumba", "#walczyk", "#świąteczne",
)
# Słownik z bazy VirtualDJ. Bez tagów jednorazowych: rok, osoba, impreza, przerwa.
BUILTIN_TAG_FIELDS = {
    "Genre": (
        "#Polskie", "#angielskie", "#francuskie", "#niemieckie", "#Latino", "#Italiano",
        "#EDM", "#House", "#Techno", "#NuDisco", "#POP", "#Dance/Disco",
        "#Rock", "#Rock'n'roll", "#Disco-Polo", "#DP-BEST", "#Hip-hop",
        "#FunkySoulRNB", "#Reggae", "#Biesiada", "#Pompa", "#Góralskie",
        "#Orientalne", "#ruskie", "#Themes", "#Famfary", "#animacje",
        "#dziecianimacja", "#Konkursy",
    ),
    "User1": (
        "#Lata50", "#Lata60-te", "#Lata70-te", "#Lata80-te", "#Lata90-te",
        "#Lata00", "#Lata10", "#Lata20",
        "#PARTY", "#EXTRAPARTY", "#Taneczne", "#ballady", "#DownTempo",
        "#POWER", "#LADIES", "#szybkie", "#Bardzostare", "#weselne",
        "#EXTRAROCK'N'ROLL",
    ),
    "User2": (
        "#1", "#2", "#3", "#4", "#5",
        "#cover", "#mashup", "#NORMAL_CLUB", "#DANCING", "#HIGH_ENERGY",
        "#WESELE", "#chillout", "#świąteczne", "#antypolo", "#country",
        "#muzykaklasyczna", "#tiktok", "#trap",
        "#cza-cza", "#Rumba", "#walczyk", "#Walcwiedeński", "#Walcangielski",
        "#Salsa", "#Samba", "#bachata", "#Baciata", "#tango", "#foxtrot",
        "#jive/boogie", "#2step", "#szanty", "#saksofon", "#śląskie", "#dzieciaki",
    ),
}
_ERA_ALIAS = {
    "lata50": "#Lata50",
    "lata60": "#Lata60-te",
    "lata70": "#Lata70-te",
    "lata80": "#Lata80-te",
    "lata90": "#Lata90-te",
    "lata00": "#Lata00",
    "lata2000": "#Lata00",
    "lata10": "#Lata10",
    "lata2010": "#Lata10",
    "lata20": "#Lata20",
    "lata2020": "#Lata20",
}


def song_hashtags(song: dict) -> list[str]:
    found = []
    for key in ("Tags.Genre", "Tags.User1", "Tags.User2"):
        for part in re.split(r"[\s,;]+", str(song.get(key) or "")):
            part = part.strip()
            if part.startswith("#") and part not in found:
                found.append(part)
    return found


def is_junk_tag(tag: str) -> bool:
    return (tag or "").strip().casefold() in _JUNK


def scheme_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if tag.startswith("#") and not is_junk_tag(tag)]


def builtin_label_map() -> dict[str, str]:
    labels = {}
    for tags in BUILTIN_TAG_FIELDS.values():
        for tag in tags:
            labels.setdefault(tag.casefold(), tag)
    return labels


def builtin_field(tag: str) -> str:
    key = (tag or "").casefold()
    for field, tags in BUILTIN_TAG_FIELDS.items():
        if any(item.casefold() == key for item in tags):
            return field
    return ""


def normalize_scheme_tag(raw: str, known: dict[str, str]) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if not text.startswith("#"):
        text = "#" + text
    key = text.casefold().lstrip("#")
    key = key.replace("ł", "l").replace(" ", "")
    if key in _ERA_ALIAS:
        text = _ERA_ALIAS[key]
        return known.get(text.casefold()) or text
    if key in {"1", "2", "3", "4", "5"}:
        return "#" + key
    if key in _LANGUAGE:
        text = _LANGUAGE[key]
        return known.get(text.casefold()) or text
    if key in _DANCE:
        text = _DANCE[key]
        return known.get(text.casefold()) or text
    if key in {"christmas", "xmas", "swiateczne", "świąteczne"}:
        text = known.get("#świąteczne") or known.get("#swiateczne") or "#świąteczne"
        return text
    known_hit = known.get(text.casefold()) or builtin_label_map().get(text.casefold())
    if known_hit:
        return known_hit
    if text.casefold() == "#świąteczne":
        return "#świąteczne"
    return ""


def parse_scheme_answer(answer: str, known: dict[str, str]) -> list[dict]:
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
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("idx"))
        except (TypeError, ValueError):
            continue
        tags = []
        for raw in item.get("tags") or []:
            tag = normalize_scheme_tag(str(raw), known)
            if tag and tag not in tags and not is_junk_tag(tag):
                tags.append(tag)
        why = str(item.get("why") or "").strip()
        if not tags:
            out.append({"idx": idx, "tags": [], "why": why or "Nie rozpoznaję tego nagrania."})
            continue
        if len(tags) < 3:
            continue
        out.append({"idx": idx, "tags": tags[:8], "why": why})
    return out


def known_tag_map(songs: list[dict]) -> dict[str, str]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for song in songs:
        for tag in song_hashtags(song):
            if is_junk_tag(tag):
                continue
            key = tag.casefold()
            counts[key] = counts.get(key, 0) + 1
            labels[key] = tag
    chosen = {key: labels[key] for key, count in counts.items() if count >= 15}
    for key, tag in builtin_label_map().items():
        chosen.setdefault(key, labels.get(key) or tag)
    for energy in _ENERGY:
        chosen[energy.casefold()] = labels.get(energy.casefold()) or energy
    for tag in _PINNED:
        chosen.setdefault(tag.casefold(), labels.get(tag.casefold()) or tag)
    return chosen


def _artist_key(song: dict) -> str:
    return " ".join(str(song.get("Tags.Author") or song.get("Tags.Artist") or "").casefold().split())


def example_rows(songs: list[dict], limit: int = 20) -> list[dict]:
    seen = set()
    rows = []
    for i, song in enumerate(songs):
        tags = scheme_tags(song_hashtags(song))
        if len(tags) < 4:
            continue
        artist = _artist_key(song)
        title = str(song.get("Tags.Title") or "").strip()
        if not artist or not title or artist in seen:
            continue
        seen.add(artist)
        rows.append({"idx": i, "author": song.get("Tags.Author") or "", "title": title, "tags": tags[:8]})
        if len(rows) >= limit:
            break
    return rows


def _default_field(tag: str) -> str:
    mapped = builtin_field(tag)
    if mapped:
        return mapped
    key = (tag or "").casefold()
    if key in {"#1", "#2", "#3", "#4", "#5", "#cover", "#mashup", "#wesele", "#dancing", "#high_energy"}:
        return "User2"
    if key.startswith("#lata") or key in {
        "#party", "#taneczne", "#ballady", "#chillout", "#świąteczne", "#swiateczne", "#downtempo",
    }:
        return "User1"
    return "Genre"


def field_owners(songs: list[dict]) -> dict[str, str]:
    """Tag -> pole, w którym ta baza trzyma go najczęściej."""
    from vdj_parser import parse_tags_value

    counts: dict[tuple[str, str], int] = {}
    for song in songs:
        for field in ("Genre", "User1", "User2"):
            for tag in parse_tags_value(str(song.get(f"Tags.{field}") or "")):
                if not tag.startswith("#") or is_junk_tag(tag):
                    continue
                key = (tag.casefold(), field)
                counts[key] = counts.get(key, 0) + 1
    best: dict[str, tuple[int, str]] = {}
    for (name, field), count in counts.items():
        current = best.get(name)
        if current is None or count > current[0]:
            best[name] = (count, field)
    return {name: field for name, (_count, field) in best.items()}


def needs_scheme(song: dict) -> bool:
    if any(tag.casefold() in {"#użytkowe", "#uzytkowe"} for tag in song_hashtags(song)):
        return False
    artist = _artist_key(song)
    title = str(song.get("Tags.Title") or "").strip()
    if not artist or not title:
        return False
    return len(scheme_tags(song_hashtags(song))) < 3


def candidate_rows(songs: list[dict], limit: int | None = None, shuffle: bool = False) -> list[dict]:
    import random

    rows = []
    for i, song in enumerate(songs):
        if not needs_scheme(song):
            continue
        rows.append({
            "idx": i,
            "author": song.get("Tags.Author") or "",
            "title": str(song.get("Tags.Title") or "").strip(),
            "tags": scheme_tags(song_hashtags(song))[:6],
            "path": song.get("FilePath") or "",
        })
    if shuffle:
        random.shuffle(rows)
    if limit is not None:
        return rows[:limit]
    return rows


def add_scheme_tags(song: dict, tags: list[str], owners: dict[str, str]) -> bool:
    from vdj_parser import join_tags, parse_tags_value

    buckets = {
        field: parse_tags_value(str(song.get(f"Tags.{field}") or ""))
        for field in ("Genre", "User1", "User2")
    }
    have = {tag.casefold() for values in buckets.values() for tag in values}
    changed = False
    for tag in tags:
        if not tag or tag.casefold() in have or is_junk_tag(tag):
            continue
        field = owners.get(tag.casefold()) or _default_field(tag)
        buckets[field].append(tag)
        have.add(tag.casefold())
        changed = True
    if not changed:
        return False
    for field, values in buckets.items():
        song[f"Tags.{field}"] = join_tags(values)
    return changed


def preview_rows(songs: list[dict], limit: int = 20) -> list[dict]:
    import random

    pool = []
    seen = set()
    for i, song in enumerate(songs):
        if any(tag.casefold() in {"#użytkowe", "#uzytkowe"} for tag in song_hashtags(song)):
            continue
        artist = _artist_key(song)
        title = str(song.get("Tags.Title") or "").strip()
        if not artist or not title or artist in seen:
            continue
        seen.add(artist)
        pool.append({
            "idx": i,
            "author": song.get("Tags.Author") or "",
            "title": title,
            "tags": scheme_tags(song_hashtags(song))[:6],
            "path": song.get("FilePath") or "",
        })
    random.shuffle(pool)
    return pool[:limit]


def scheme_prompt(examples: list[dict], targets: list[dict], allowed: list[str]) -> str:
    example_lines = [
        f'{row["author"]}\t{row["title"]}\t{" ".join(row["tags"])}'
        for row in examples
    ]
    target_lines = [
        f'{row["idx"]}\t{row["author"]}\t{row["title"]}\t{" ".join(row["tags"])}'
        for row in targets
    ]
    return (
        "Dopisz tagi tylko wtedy, gdy rozpoznajesz oficjalnie wydany utwór. "
        "Jak nie jesteś pewien, oddaj tags: []. Nie zgaduj po nicku ani po nazwie pliku. "
        "Nie taguj zapowiedzi, intro, podkładu pod quiz ani utworu zrobionego na zamówienie. "
        "Przykłady bez tagów: marksilvermoon — Ladies and gentleman, panie i panowie; "
        "nowaczykdamian — Steel & Saltwater. "
        "Gdy jesteś pewien, daj około 6 tagów z listy dozwolonych: "
        "epoka (#Lata70-te, #Lata80-te, #Lata90-te, #Lata00, #Lata10 albo #Lata20), "
        "jeden albo dwa ogólne gatunki, rodzaj (#PARTY, #Taneczne, #ballady, #cover, #mashup, #WESELE, #chillout, #świąteczne) "
        "i język śpiewu. "
        "Język: #Polskie, #francuskie, #niemieckie, #angielskie. "
        "Hiszpański, portugalski i brazylijski to jeden tag #Latino, bez podziału na kraj. "
        "Nie używaj #PolishLatino. Przy polskim latino daj #Polskie i #Latino osobno. "
        "Jak języka nie rozpoznajesz, nie dodawaj go. "
        "Taniec tylko gdy utwór ewidentnie nim jest. Bierz tag z listy dozwolonych: "
        "#cza-cza, #Rumba, #walczyk, #Walcwiedeński, #Walcangielski, #Salsa, #Samba, #bachata, #tango, #foxtrot. "
        "Zwykłe latino, pop albo house nie dostaje tagu tańca. "
        "Energia #1 #2 #3 #4 #5 to moc, przebojowość i energia muzyczna. To nie tempo i nie gatunek. "
        "Utwór z lat 80 może mieć #1 albo #5. Disco polo może mieć #1 albo #5. "
        "Jak energii nie czujesz, nie dodawaj numeru. "
        "Znany utwór świąteczny dostaje #świąteczne, na przykład Mariah Carey — All I Want For Christmas Is You. "
        "Wzór: Lady Pank, Zawsze tam gdzie ty → #Rock #ballady #Lata00 #Polskie #1. "
        "Tiësto, Traffic → #Techno #Lata00 #PARTY #5. "
        "Odpowiedź to sam JSON, po jednym wpisie na każdy idx: "
        '[{"idx": 1, "tags": ["#Rock", "#Lata00", "#Polskie", "#ballady", "#1"], "why": "krótko"}]. '
        'Niepewny utwór: {"idx": 2, "tags": [], "why": "nie znam tego nagrania"}.\n'
        "Dozwolone tagi: " + " ".join(allowed) + "\n"
        "Przykłady z tej bazy, wykonawca, tytuł, tagi:\n"
        + "\n".join(example_lines)
        + "\nDo otagowania, idx, wykonawca, tytuł, tagi które już są:\n"
        + "\n".join(target_lines)
    )
