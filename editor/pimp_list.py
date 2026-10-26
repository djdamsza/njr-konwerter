"""Pimp my list: podsumowanie playlisty i paczki po 20 przebojów.

Udana odpowiedź AI ściąga token z konta na stronie. Nieudane
wywołanie modelu tokenu nie zużywa. Nic tu nie pobiera plików.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

from dup_marks import author_key, bpm_of, core_title

BATCH = 20
PIMP_TRACKS_PER_TOKEN = 300
PIMP_PROMPT_CHARS = 150_000

_WEIRD = re.compile(
    r"\b(remix|bootleg|mashup|mash-up|flip|rework|extended|club mix|dub mix)\b",
    re.I,
)
_HARD = re.compile(r"\b(bootleg|mashup|mash-up|flip|rework|rmx|remix)\b", re.I)
_CLUB = ("techno", "house", "trance", "edm", "electro", "rave")
_FLOOR = ("wesele", "wedding", "pop", "disco", "dance", "przeboj", "party", "zabawa")

_tokens_spent = 0
_balance = None
_balance_ready = False


def tokens_spent() -> int:
    return _tokens_spent


def set_token_balance(value) -> None:
    """Stan z konta na stronie. None znaczy, że konta jeszcze nie odczytano."""
    global _balance, _balance_ready
    if value is None or value == "":
        _balance = None
    else:
        _balance = max(0, int(value))
    _balance_ready = True


def token_balance():
    """Ile tokenów zostało na koncie. None, dopóki strona nie poda stanu."""
    return _balance


def has_tokens(need: int = 1) -> bool:
    """AI rusza tylko, gdy konto na stronie ma dość tokenów."""
    balance = token_balance()
    if balance is None:
        return False
    return balance >= max(1, int(need or 1))


def tokens_for_thousand(count: int) -> int:
    """1 token za każde rozpoczęte 1000. 6000 utworów = 6 tokenów."""
    n = max(0, int(count or 0))
    if n <= 0:
        return 0
    return (n + 999) // 1000


def charge_token() -> int:
    return charge_tokens(1)


def charge_tokens(count: int) -> int:
    """Ściąga tokeny z konta na stronie. Lokalnie nic nie odejmuje."""
    global _tokens_spent
    n = max(0, int(count or 0))
    if n <= 0:
        return _tokens_spent
    # #region agent log
    try:
        import json, time, traceback
        caller = traceback.extract_stack(limit=4)[-2]
        with open("/Users/test/Documents/njr-konwerter/.cursor/debug-2001e2.log", "a", encoding="utf-8") as _df:
            _df.write(json.dumps({"sessionId": "2001e2", "hypothesisId": "A", "location": "pimp_list.py:charge_tokens", "message": "token charge", "data": {"count": n, "caller": caller.name, "file": caller.filename.rsplit("/", 1)[-1], "line": caller.lineno}, "timestamp": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    from njr_account import spend_tokens
    payload = spend_tokens(n)
    set_token_balance(payload.get("tokens") if payload.get("tokens") is not None else 0)
    _tokens_spent += n
    return _tokens_spent


def reset_tokens() -> None:
    global _tokens_spent, _balance, _balance_ready
    _tokens_spent = 0
    _balance = None
    _balance_ready = False


def is_weird_remix(title: str) -> bool:
    return bool(_WEIRD.search(title or ""))


def prefer_local_options(disks: list, tidal: list) -> tuple[list, int]:
    """Plik z dysku jest pierwszy i zaznaczony. Remix zostaje na końcu i sam się nie zaznacza."""
    def plain(opt: dict) -> bool:
        return not is_weird_remix(opt.get("title") or "")

    plain_disk = [row for row in disks or [] if plain(row)]
    weird_disk = [row for row in disks or [] if not plain(row)]
    plain_tidal = [row for row in tidal or [] if plain(row)]
    weird_tidal = [row for row in tidal or [] if not plain(row)]
    options = plain_disk + plain_tidal + weird_disk + weird_tidal
    preferred = 0 if (plain_disk or plain_tidal) else -1
    return options, preferred


_ARTIST_STOP = {
    "the", "and", "feat", "ft", "featuring", "vs", "with",
}


def version_distance(title: str) -> int:
    """0 to wersja zwykła. Im wyżej, tym dalej od oryginału."""
    text = title or ""
    if re.search(r"\b(remix|rmx|bootleg|mashup|mash-up|flip|rework)\b", text, re.I):
        return 3
    if re.search(r"\b(live|acoustic|unplugged|karaoke|instrumental|orchestral|tabata)\b", text, re.I):
        return 3
    if re.search(r"\b(extended|club|dub)\b", text, re.I):
        return 3
    if re.search(r"\boriginal\b", text, re.I):
        return 0
    if re.search(r"\b(radio|remaster|remastered|clean|album)\b", text, re.I):
        return 0
    if re.search(r"\b(edit|mix|version)\b", text, re.I):
        return 2
    return 0


def with_version(title: str, version: str) -> str:
    """Dopisek Tidal z pola version, gdy nie ma go w tytule: Radio Edit, Remix, Live."""
    title = (title or "").strip()
    version = (version or "").strip()
    if not version:
        return title
    if version.lower() in title.lower():
        return title
    return f"{title} ({version})"


_JUNK_RECORDING = re.compile(
    r"karaoke|in the style of|originally performed|backing track|made popular by|tribute\b",
    re.I,
)
_SHARED_STANDARD = {"bialy mis"}


def _fold_name(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text or "")
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.replace("ł", "l").replace("Ł", "L")
    return author_key(raw)


def _primary_name(name: str) -> str:
    text = _fold_name(name)
    return re.split(r"\b(?:feat|ft|featuring|vs)\b", text)[0].strip()


def _name_people(name: str) -> set[str]:
    text = re.sub(r"\b(feat|ft|featuring|vs|with)\b", " ", _fold_name(name))
    return {word for word in text.split() if len(word) > 2 and word not in _ARTIST_STOP}


def _recording_people(artist: str, title: str) -> set[str]:
    people = _name_people(artist) | _title_people(title)
    match = re.search(r"\b(?:feat|ft|featuring)\.?\s+([^()\[\]]+)", title or "", re.I)
    if match:
        people |= _name_people(match.group(1))
    return people


def _clock_seconds(value) -> int:
    text = str(value or "").strip()
    if not text or text in {"—", "-", "None"}:
        return 0
    if ":" in text:
        try:
            nums = [float(bit) for bit in text.split(":")]
        except ValueError:
            return 0
        if len(nums) == 2:
            return int(nums[0] * 60 + nums[1])
        if len(nums) == 3:
            return int(nums[0] * 3600 + nums[1] * 60 + nums[2])
        return 0
    try:
        n = float(text)
    except ValueError:
        return 0
    if n > 10000:
        n = n / 1000.0
    return int(n) if n > 0 else 0


def _bpm_rank(origin, candidate) -> int:
    left, right = bpm_of(origin), bpm_of(candidate)
    if left <= 0 or right <= 0:
        return 1
    diff = abs(left - right)
    if diff <= 1:
        return 0
    if diff <= 4:
        return 1
    return 3


def _duration_rank(origin: int, candidate: int) -> int:
    if origin <= 0 or candidate <= 0:
        return 2
    diff = abs(origin - candidate)
    if diff <= 8:
        return 0
    if diff <= 20:
        return 1
    if diff <= 45:
        return 2
    return 4


def _shared_standard(title: str) -> bool:
    bare = _fold_name(_bare_title(title))
    bare = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", bare)
    return " ".join(bare.split()) in _SHARED_STANDARD


def _same_artist(origin_artist: str, origin_title: str, cand_artist: str, cand_title: str) -> bool:
    """Inny wykonawca z tym samym tytułem to zwykle inna piosenka."""
    if _shared_standard(origin_title):
        return True
    left = _primary_name(origin_artist)
    right = _primary_name(cand_artist)
    if left and right and left == right:
        return True
    if left and right and len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return True
    origin = _recording_people(origin_artist, origin_title)
    cand = _recording_people(cand_artist, cand_title)
    if origin and cand and origin & cand:
        return True
    compact_l = left.replace(" ", "")
    compact_r = right.replace(" ", "")
    if len(compact_l) >= 4 and len(compact_r) >= 4 and abs(len(compact_l) - len(compact_r)) <= 1:
        return _distance(compact_l, compact_r) <= 1
    return False


def _person_tokens(name: str) -> set[str]:
    text = author_key(name)
    text = re.sub(r"\b(feat|ft|featuring|vs|with)\b", " ", text)
    return {word for word in text.split() if len(word) > 1 and word not in _ARTIST_STOP}


def _title_people(title: str) -> set[str]:
    found = set()
    for note in re.findall(r"\(([^)]+)\)|\[([^\]]+)\]", title or ""):
        chunk = note[0] or note[1]
        words = re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", chunk.lower()).split()
        found.update(
            word for word in words
            if len(word) > 1 and not _VERSION_WORD.match(word) and word not in _ARTIST_STOP
        )
    return found


def _bare_title(title: str) -> str:
    """Zdejmuje dopisek feat., żeby „100 feat. X” i „100” zostały tym samym utworem."""
    text = re.sub(
        r"\s*[\(\[][^)\]]*(?:feat|ft|featuring)[^)\]]*[\)\]]",
        " ",
        title or "",
        flags=re.I,
    )
    text = re.sub(r"\b(?:feat|ft|featuring)\.?\s+.*$", " ", text, flags=re.I)
    return " ".join(text.split())


def same_recording(origin: str, candidate: str) -> bool:
    """Ten sam utwór. Inna piosenka tego samego wykonawcy odpada."""
    if same_song(origin, candidate):
        return True
    return same_song(_bare_title(origin), _bare_title(candidate))


def rank_replacements(artist: str, title: str, options: list, duration="", bpm="") -> tuple[list, int]:
    """Zostawia ten sam utwór tego samego wykonawcy. Brak zamiennika jest poprawną odpowiedzią.

    Wyjątek: utwór ludowy z listy (Biały miś) zostaje u innych wykonawców.
    Zaznaczenie dostaje pierwsza pozycja, o ile nie jest remiksem, live ani karaoke.
    """
    origin = _recording_people(artist, title)
    origin_seconds = _clock_seconds(duration)
    kept = []
    for opt in options or []:
        cand_title = opt.get("title") or ""
        cand_artist = opt.get("author") or opt.get("artist") or ""
        blob = f"{cand_title} {cand_artist}"
        if _JUNK_RECORDING.search(blob):
            continue
        if not same_recording(title, cand_title):
            continue
        if not _same_artist(artist, title, cand_artist, cand_title):
            continue
        kept.append(opt)

    def sort_key(opt: dict) -> tuple:
        cand_title = opt.get("title") or ""
        cand_artist = opt.get("author") or opt.get("artist") or ""
        people = _recording_people(cand_artist, cand_title)
        left = _primary_name(artist).replace(" ", "")
        right = _primary_name(cand_artist).replace(" ", "")
        same_primary = bool(
            left and right and len(left) >= 4 and abs(len(left) - len(right)) <= 1
            and _distance(left, right) <= 1
        )
        if same_primary:
            extra = len(_title_people(cand_title) - _title_people(title))
            missing = 0
        else:
            extra = len(people - origin)
            missing = len(origin - people)
        timing = _duration_rank(origin_seconds, _clock_seconds(opt.get("duration")))
        tempo = _bpm_rank(bpm, opt.get("bpm"))
        local = 0 if opt.get("kind") == "disk" else 1
        return (version_distance(cand_title), extra, missing, timing, tempo, local)

    kept.sort(key=sort_key)
    if not kept or version_distance(kept[0].get("title") or "") >= 3:
        return kept[:6], -1
    return kept[:6], 0


def track_key(author: str, title: str) -> tuple[str, str]:
    return author_key(author), core_title(title)


def _year(value) -> int:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else 0


def _tags(row: dict) -> list[str]:
    blob = " ".join(
        str(row.get(name) or "")
        for name in ("genre", "user1", "user2")
    ).lower()
    return [part.strip() for part in re.split(r"[,/;|#]+", blob) if part.strip()]


def is_disk_row(row: dict) -> bool:
    if row.get("streaming") or row.get("cache"):
        return False
    path = (row.get("path") or "").strip()
    return bool(path) and not is_weird_remix(row.get("title") or "")


def facts(tracks: list[dict]) -> dict:
    artists: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    bpms = []
    years = []
    for row in tracks:
        author = (row.get("author") or "").strip()
        if author:
            artists[author] += 1
        for tag in _tags(row):
            genres[tag.strip()] += 1
        bpm = bpm_of(row.get("bpm"))
        if bpm > 0:
            bpms.append(bpm)
        year = _year(row.get("year"))
        if year:
            years.append(year)
    blob = " ".join(list(genres) + [a.lower() for a in artists])
    mixed = any(word in blob for word in _CLUB) and any(word in blob for word in _FLOOR)
    bpms.sort()
    mid = bpms[len(bpms) // 2] if bpms else 0
    return {
        "count": len(tracks),
        "artists": artists.most_common(12),
        "genres": [name for name, _n in genres.most_common(12)],
        "bpm_mid": mid,
        "year_min": min(years) if years else 0,
        "year_max": max(years) if years else 0,
        "mixed": mixed,
    }


def local_summary(name: str, info: dict) -> str:
    bits = [f"Lista „{name}”: {info['count']} utworów."]
    if info["artists"]:
        bits.append("Najczęściej: " + ", ".join(artist for artist, _n in info["artists"][:8]) + ".")
    if info["genres"]:
        bits.append("Tagi: " + ", ".join(info["genres"][:8]) + ".")
    if info["year_min"]:
        bits.append(f"Lata {info['year_min']}–{info['year_max']}.")
    if info["bpm_mid"]:
        bits.append(f"Tempo okolice {info['bpm_mid']:.0f} BPM.")
    if info["mixed"]:
        bits.append(
            "Widać dwa światy naraz. Propozycje pójdą w hity, które łączą oba, "
            "na przykład klubowy numer znany z wesela."
        )
    return " ".join(bits)


def pimp_read_tokens(count: int) -> int:
    """1 token za każde rozpoczęte 300 utworów wysłanych do modelu."""
    n = max(0, int(count or 0))
    if n <= 0:
        return 0
    return (n + PIMP_TRACKS_PER_TOKEN - 1) // PIMP_TRACKS_PER_TOKEN


def _playlist_lines(tracks: list[dict]) -> list[str]:
    lines = []
    seen = set()
    for row in tracks:
        author = (row.get("author") or "").strip()
        title = (row.get("title") or "").strip()
        key = (author_key(author), _compact_title(title))
        if len(key[1]) < 2 or key in seen:
            continue
        seen.add(key)
        lines.append(f"{author} - {title}")
    return lines


def pimp_slices(tracks: list[dict]) -> list[list[dict]]:
    """Cała lista w jednym zapytaniu. Powyżej limitu znaków idzie w odczytach po 300."""
    if not tracks:
        return []
    body = sum(len(line) + 1 for line in _playlist_lines(tracks))
    if body + 6000 <= PIMP_PROMPT_CHARS:
        return [tracks]
    size = PIMP_TRACKS_PER_TOKEN
    return [tracks[i:i + size] for i in range(0, len(tracks), size)]


def _sample_lines(tracks: list[dict], limit: int = 40) -> list[str]:
    if len(tracks) <= limit:
        chosen = tracks
    else:
        step = max(1, len(tracks) // limit)
        chosen = tracks[::step][:limit]
    lines = []
    for row in chosen:
        author = (row.get("author") or "").strip()
        title = (row.get("title") or "").strip()
        if author or title:
            lines.append(f"{author} - {title}")
    return lines


def summary_prompt(name: str, info: dict, tracks: list[dict]) -> str:
    lines = "\n".join(_playlist_lines(tracks))
    return (
        "Opisz po polsku klimat playlisty DJ-skiej. Bez listy propozycji i bez rad, co dodać.\n"
        "4–6 zdań: gatunki, lata, nastrój, kto się powtarza. "
        "Gdy lista łączy dwa światy, nazwij oba.\n"
        f"Lista: {name}\n"
        f"{local_summary(name, info)}\n"
        f"Utwory:\n{lines}"
    )


def disk_candidates(
    rows: list[dict],
    on_list: set[tuple[str, str]],
    info: dict,
    limit: int = 40,
    playlist_rows: list[dict] | None = None,
) -> list[dict]:
    artist_weight = {author_key(name): count for name, count in info["artists"]}
    genre_weight = {tag.lower(): 1 for tag in info["genres"]}
    bpm_mid = info["bpm_mid"] or 0
    ranked = []
    for row in rows:
        if not is_disk_row(row):
            continue
        key = track_key(row.get("author") or "", row.get("title") or "")
        if len(key[0]) < 2 or len(key[1]) < 2 or key in on_list:
            continue
        if on_playlist(row.get("author") or "", row.get("title") or "", playlist_rows):
            continue
        score = artist_weight.get(key[0], 0) * 5
        for tag in _tags(row):
            if tag.lower() in genre_weight:
                score += 2
        if score <= 0:
            continue
        bpm = bpm_of(row.get("bpm"))
        if bpm_mid and bpm and abs(bpm - bpm_mid) <= 8:
            score += 2
        try:
            plays = int(float(row.get("playcount") or 0))
        except (TypeError, ValueError):
            plays = 0
        ranked.append((score, plays, row, key))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    out = []
    seen = set()
    for score, _plays, row, key in ranked:
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": f"D{len(out) + 1}",
            "key": key,
            "idx": row.get("idx"),
            "path": row.get("path") or "",
            "author": row.get("author") or "",
            "title": row.get("title") or "",
            "genre": row.get("genre") or "",
            "score": score,
        })
        if len(out) >= limit:
            break
    return out


def suggest_prompt(name: str, info: dict, tracks: list[dict], note: str, candidates: list[dict], exclude: list[dict]) -> str:
    del info
    lines = _playlist_lines(tracks)
    owned = "\n".join(
        f"{row['id']}: {row['author']} - {row['title']}"
        for row in candidates
    ) or "(brak)"
    skipped = "\n".join(
        f"{(row.get('artist') or row.get('author') or '').strip()} - {(row.get('title') or '').strip()}"
        for row in exclude
        if (row.get("title") or "").strip()
    )
    direction = (note or "").strip()[:400]
    return (
        "Dostajesz pełną listę nagrań, które już są na playliście. Nie dostajesz opisu klimatu.\n"
        "Podaj dokładnie 20 innych przebojów, których na tej liście nie ma, a które powinny tu być.\n"
        "Ten sam utwór jako radio edit, remix, extended albo cover też już jest. Nie proponuj go.\n"
        "Zostań przy gatunku i energii tych nagrań.\n"
        "Odpowiedz wyłącznie JSON:\n"
        '{"klimat":"jedno zdanie, jak rozumiesz te nagrania","propozycje":['
        '{"zrodlo":"dysk","id":"D1","dlaczego":"krótko"}'
        ',{"zrodlo":"brak","artysta":"Pitbull","tytul":"Give Me Everything","dlaczego":"krótko"}]}\n'
        f"Nagrania już na liście ({len(lines)}):\n" + "\n".join(lines) + "\n"
        + (f"Dopisek użytkownika: {direction}\n" if direction else "")
        + f"Pliki z dysku, których na liście nie ma:\n{owned}\n"
        + f"Nie powtarzaj wcześniejszych propozycji:\n{skipped or '(nic)'}"
    )


def parse_model_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model nie oddał listy propozycji.")
    data = json.loads(raw[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Model nie oddał listy propozycji.")
    return data


_VERSION_WORD = re.compile(
    r"^(radio|remix|mix|edit|extended|version|clean|club|original|dub|acoustic|live|"
    r"instrumental|bootleg|cover|rework|rmx|flip|short|album|dj|remaster|remastered|reedit)$",
    re.I,
)


def _title_words(title: str) -> list[str]:
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title or "")
    text = re.sub(r"[^a-z0-9ąćęłńóśźż ]", " ", (text or "").lower())
    return [word for word in text.split() if word]


def _compact_title(title: str) -> str:
    return "".join(_title_words(title))


def _version_tail(extra: list[str]) -> bool:
    """Zostaje tylko dopisek wersji: Endriu Bootleg, Tiesto Remix. Reggae już nie."""
    if not extra or len(extra) > 4:
        return False
    names = [word for word in extra if not _VERSION_WORD.match(word)]
    marks = [word for word in extra if _VERSION_WORD.match(word)]
    return bool(marks) and len(names) <= 2


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 2:
        return 9
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(
                previous[j] + 1,
                current[-1] + 1,
                previous[j - 1] + (char != other),
            ))
        previous = current
    return previous[-1]


def artists_match(left: str, right: str) -> bool:
    a = author_key(left)
    b = author_key(right)
    if len(a) < 2 or len(b) < 2:
        return False
    if a == b:
        return True

    def primary(name: str) -> str:
        return re.split(r"\b(?:feat|ft|featuring|vs)\b", name)[0].strip()

    pa, pb = primary(a), primary(b)
    return bool(pa and pa == pb)


def titles_match(left: str, right: str) -> bool:
    """Ten sam utwór albo literówka w dłuższym tytule. Maria i Magia to nie literówka."""
    left_key = _compact_title(left)
    right_key = _compact_title(right)
    if left_key == right_key:
        return len(left_key) >= 2
    short = min(len(left_key), len(right_key))
    if short < 7:
        return False
    if short < 12:
        if len(left_key) != len(right_key):
            return False
        return _distance(left_key, right_key) == 1
    if abs(len(left_key) - len(right_key)) > 2:
        return False
    return _distance(left_key, right_key) <= 2


def same_song(left: str, right: str) -> bool:
    if titles_match(left, right):
        return True
    a = _title_words(left)
    b = _title_words(right)
    if len(a) >= 2 and b[:len(a)] == a and _version_tail(b[len(a):]):
        return True
    if len(b) >= 2 and a[:len(b)] == b and _version_tail(a[len(b):]):
        return True
    return False


def _usable_disk(row: dict) -> bool:
    if row.get("streaming") or row.get("cache"):
        return False
    if not (row.get("path") or "").strip():
        return False
    return not _HARD.search(row.get("title") or "")


def _file_score(row: dict) -> int:
    title = (row.get("title") or "").lower()
    score = 0
    if re.search(r"\b(radio|clean|short|album)\b", title):
        score += 50
    if "extended" in title:
        score += 10
    try:
        score += min(int(float(row.get("playcount") or 0)), 20)
    except (TypeError, ValueError):
        pass
    return score


def find_on_disk(artist: str, title: str, rows: list[dict]) -> dict | None:
    """Szuka utworu w kolekcji także przy innej pisowni tytułu."""
    best = None
    best_score = -1
    for row in rows:
        if not _usable_disk(row):
            continue
        if not artists_match(artist, row.get("author") or ""):
            continue
        if not titles_match(title, row.get("title") or ""):
            continue
        score = _file_score(row)
        if score > best_score:
            best = row
            best_score = score
    return best


def on_playlist(artist: str, title: str, rows: list[dict] | None) -> bool:
    """Ten sam przebój, także radio edit albo inna wielkość liter."""
    for row in rows or []:
        their_author = row.get("author") or ""
        their_title = row.get("title") or ""
        if not their_title.strip():
            continue
        if not artists_match(artist, their_author):
            continue
        if same_song(title, their_title) or titles_match(title, their_title):
            return True
    return False


def _path_on_playlist(path: str, rows: list[dict] | None) -> bool:
    want = (path or "").strip()
    if not want:
        return False
    for row in rows or []:
        if (row.get("path") or "").strip() == want:
            return True
    return False


def is_original_like(title: str) -> bool:
    text = title or ""
    if re.search(r"\b(remix|bootleg|cover|rework|rmx|flip|edit|extended)\b", text, re.I):
        return False
    if re.search(r"\boriginal\b", text, re.I):
        return True
    return not re.search(r"\bmix\b", text, re.I)


def _version_label(row: dict, parent_artist: str) -> str:
    title = row.get("title") or ""
    author = row.get("author") or ""
    notes = re.findall(r"\(([^)]+)\)", title)
    if re.search(r"\bcover\b", title, re.I) or (
        not artists_match(author, parent_artist) and notes
    ):
        tail = notes[-1] if notes else "cover"
        return f"Wersja na dysku: {author} — {tail}"
    if notes:
        return "Wersja na dysku: " + notes[-1]
    if not artists_match(author, parent_artist):
        return f"Inna wersja na dysku: {author}"
    return "Wersja na dysku"


def collect_versions(artist: str, title: str, rows: list[dict]) -> list[dict]:
    """Inne wersje tego samego utworu z dysku: edit, remix, extended, cover."""
    found = []
    seen = set()
    for row in rows:
        if row.get("streaming") or row.get("cache"):
            continue
        path = (row.get("path") or "").strip()
        if not path or path in seen:
            continue
        if not same_song(title, row.get("title") or ""):
            continue
        same_artist = artists_match(artist, row.get("author") or "")
        blob = f"{row.get('title') or ''} {row.get('author') or ''}"
        if not same_artist and not re.search(r"\b(remix|edit|cover|bootleg|rmx|extended|mix)\b", blob, re.I):
            continue
        seen.add(path)
        found.append(row)
    found.sort(key=lambda row: (-_file_score(row), row.get("title") or ""))
    return found


def version_entries(artist: str, title: str, rows: list[dict], parent_path: str, playlist_rows: list[dict] | None) -> list[dict]:
    out = []
    for row in collect_versions(artist, title, rows):
        path = (row.get("path") or "").strip()
        if parent_path and path == parent_path:
            continue
        if len(out) >= 8:
            break
        out.append({
            "kind": "disk",
            "artist": row.get("author") or "",
            "title": row.get("title") or "",
            "why": _version_label(row, artist),
            "path": path,
            "idx": row.get("idx"),
            "already": _path_on_playlist(path, playlist_rows),
        })
    return out


def _best_disk(rows: list[dict], on_list: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    found: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not is_disk_row(row):
            continue
        key = track_key(row.get("author") or "", row.get("title") or "")
        if len(key[0]) < 2 or len(key[1]) < 2 or key in on_list:
            continue
        previous = found.get(key)
        if previous is None:
            found[key] = row
            continue
        try:
            old_plays = int(float(previous.get("playcount") or 0))
            new_plays = int(float(row.get("playcount") or 0))
        except (TypeError, ValueError):
            old_plays, new_plays = 0, 0
        if new_plays > old_plays:
            found[key] = row
    return found


def materialize(
    data: dict,
    candidates: list[dict],
    rows: list[dict],
    on_list: set[tuple[str, str]],
    exclude: set[tuple[str, str]] | None = None,
    playlist_rows: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Zamienia JSON modelu na wiersze dysk albo Tidal. Bez plików spoza kolekcji."""
    by_id = {row["id"]: row for row in candidates}
    blocked = set(on_list)
    blocked.update(exclude or ())
    climate = str(data.get("klimat") or "").strip()[:500]
    out = []
    seen = set()
    for item in data.get("propozycje") or []:
        if len(out) >= BATCH or not isinstance(item, dict):
            continue
        why = str(item.get("dlaczego") or "").strip()[:240]
        source = str(item.get("zrodlo") or "").lower()
        picked = by_id.get(str(item.get("id") or "").strip()) if source == "dysk" else None
        if picked is not None:
            artist = (picked.get("author") or "").strip()
            title = (picked.get("title") or "").strip()
        else:
            artist = str(item.get("artysta") or item.get("author") or "").strip()
            title = str(item.get("tytul") or item.get("title") or "").strip()
        if is_weird_remix(title):
            continue
        key = track_key(artist, title)
        if len(key[1]) < 2 or key in seen:
            continue
        seen.add(key)
        if on_playlist(artist, title, playlist_rows) or key in blocked:
            continue
        owned = [row for row in collect_versions(artist, title, rows) if is_original_like(row.get("title") or "")]
        owned.sort(key=lambda row: -_file_score(row))
        versions = [
            row for row in version_entries(artist, title, rows, "", playlist_rows)
            if not row.get("already")
        ]
        if any(_path_on_playlist(row.get("path") or "", playlist_rows) for row in collect_versions(artist, title, rows)):
            continue
        if owned:
            parent = owned[0]
            path = parent.get("path") or ""
            if _path_on_playlist(path, playlist_rows):
                continue
            out.append({
                "kind": "disk",
                "artist": parent.get("author") or artist,
                "title": parent.get("title") or title,
                "why": why or "Masz ten przebój na dysku, a na tej liście go nie ma.",
                "path": path,
                "idx": parent.get("idx"),
                "already": False,
                "versions": [row for row in versions if row.get("path") != path],
            })
            continue
        plain = " ".join(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title).split()) or title
        out.append({
            "kind": "tidal",
            "artist": artist,
            "title": plain,
            "why": why,
            "path": "",
            "idx": None,
            "already": False,
            "versions": versions,
        })
    return climate, out


def pick_tidal_hit(results: list[dict], artist: str, title: str) -> dict | None:
    """Wybiera wynik Tidal o tym samym wykonawcy i tytule. Pierwszy z brzegu nie wchodzi."""
    want_author = author_key(artist)
    want_title = core_title(title)
    if len(want_author) < 2 or len(want_title) < 2:
        return None
    for row in results or []:
        if is_weird_remix(row.get("title") or ""):
            continue
        if author_key(row.get("artist") or "") == want_author and core_title(row.get("title") or "") == want_title:
            return row
    for row in results or []:
        if is_weird_remix(row.get("title") or ""):
            continue
        got_author = author_key(row.get("artist") or "")
        got_title = core_title(row.get("title") or "")
        if want_title == got_title and (want_author in got_author or got_author in want_author):
            return row
    return None


def streaming_path(source: str, tidal_id: str) -> str:
    tid = str(tidal_id or "").strip()
    if not tid.isdigit():
        return ""
    if (source or "").lower() == "vdj":
        return f"netsearch://td{tid}"
    if (source or "").lower() == "rekordbox":
        return f"file://localhosttidal:tracks:{tid}"
    return f"streaming://tidal/{tid}"
