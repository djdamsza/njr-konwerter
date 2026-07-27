"""
Serato Smart Crates (.scrate) — reguły filtrów jak VDJ Filter Folders.

Format binarny (tag 4B + length BE + data), zgodny z Serato ScratchLive Smart Crate 1.0.
Źródło pól: serato-tools / Mixxx wiki.
"""
from __future__ import annotations

import re
import struct
from io import BytesIO
from typing import Optional

# Pola reguł (urkt)
RULE_FIELD_GENRE = 9
RULE_FIELD_ARTIST = 7
RULE_FIELD_SONG = 6
RULE_FIELD_BPM = 15
RULE_FIELD_COMMENT = 17
RULE_FIELD_YEAR = 23
RULE_FIELD_PLAYS = 79
RULE_FIELD_GROUPING = 19
RULE_FIELD_FILENAME = 4
RULE_FIELD_ALBUM = 8
RULE_FIELD_KEY = 51

CMP_CONTAINS = "cond_con_str"
CMP_NOT_CONTAINS = "cond_dnc_str"
CMP_IS = "cond_is_str"
CMP_IS_NOT = "cond_isn_str"
CMP_GE = "cond_greq_uint"
CMP_LE = "cond_lseq_uint"

_TAG_HAS_RE = re.compile(
    r"(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+[\"']?([^\"'\s]+)[\"']?",
    re.IGNORECASE,
)
_TAG_CONTAINS_RE = re.compile(
    r"(?:user\s*1|user\s*2|genre)\s+contains\s+[\"']?([^\"']+)[\"']?",
    re.IGNORECASE,
)
_GENRE_IS_RE = re.compile(
    r"genre\s+is\s+[\"']?#?([^\"'\s]+)[\"']?",
    re.IGNORECASE,
)
_ARTIST_CONTAINS_RE = re.compile(
    r"artist\s+contains\s+[\"']?([^\"']+)[\"']?",
    re.IGNORECASE,
)
_TITLE_CONTAINS_RE = re.compile(
    r"(?:title|song)\s+contains\s+[\"']?([^\"']+)[\"']?",
    re.IGNORECASE,
)
_COMMENT_CONTAINS_RE = re.compile(
    r"comment\s+contains\s+[\"']?([^\"']+)[\"']?",
    re.IGNORECASE,
)
_BPM_GTE_RE = re.compile(r"bpm\s*>=\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_BPM_LTE_RE = re.compile(r"bpm\s*<=\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_YEAR_IS_RE = re.compile(r"year\s+is\s+(\d{4})", re.IGNORECASE)
_YEAR_GTE_RE = re.compile(r"year\s*>=\s*(\d{4})", re.IGNORECASE)
_PLAY_COUNT_GTE_RE = re.compile(r"play\s+count\s*>=\s*(\d+)", re.IGNORECASE)


def _encode_utf16be(s: str) -> bytes:
    return (s or "").encode("utf-16-be")


def _write_rec(buf: BytesIO, tag: str, data: bytes) -> None:
    buf.write(tag.encode("ascii"))
    buf.write(struct.pack(">I", len(data)))
    buf.write(data)


def _write_bool_nested(tag: str, value: bool) -> bytes:
    inner = BytesIO()
    _write_rec(inner, "brut", struct.pack("?", bool(value)))
    return inner.getvalue()


def _write_u32(tag: str, value: int) -> bytes:
    return struct.pack(">I", int(value) & 0xFFFFFFFF)


# Kotwice w polu Genre Serato — CONTAINS "§1§" nie łapie "§18stka§"
TAG_ANCHOR = "\u00a7"
_ANCHOR_TOKEN_RE = re.compile(r"\u00a7[^\u00a7]+\u00a7")


def normalize_tag_key(tag: str) -> str:
    """Klucz tagu: lowercase, bez spacji/underscore (normal club ≡ NORMAL_CLUB)."""
    t = (tag or "").strip().lstrip("#").lower()
    return re.sub(r"[\s_\-]+", "", t)


def serato_tag_anchor(tag: str) -> str:
    """Unikalny token do reguł Smart Crate (has tag / genre is)."""
    t = normalize_tag_key(tag)
    if not t:
        return ""
    return f"{TAG_ANCHOR}{t}{TAG_ANCHOR}"


def _extract_has_tag_value(cond: str) -> Optional[str]:
    """Wyciąga wartość z „User N has tag …” (cudzysłowy / apostrofy / jeden token)."""
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


def strip_serato_tag_anchors(genre: str) -> str:
    """Usuwa kotwice §…§ z pola Genre (np. przed ponownym zapisem)."""
    cleaned = _ANCHOR_TOKEN_RE.sub(" ", genre or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def build_serato_genre_field(
    genre: str = "",
    user1: str = "",
    user2: str = "",
) -> str:
    """Genre Serato = tagi VDJ (Genre + User1 + User2) jako #tagi."""
    from vdj_parser import parse_tags_value

    tokens: list[str] = []
    seen: set[str] = set()
    for raw in (genre, user1, user2):
        for t in parse_tags_value(raw or ""):
            key = normalize_tag_key(t)
            if not key or key in seen:
                continue
            seen.add(key)
            tokens.append(t if t.startswith("#") else f"#{t}")
    return " ".join(tokens)


def _tag_token(raw: str) -> str:
    """Nazwa tagu bez # (do kotwicy)."""
    return (raw or "").strip().lstrip("#")


def _condition_to_serato_rule(cond: str) -> Optional[dict]:
    """
    Tylko warunki TAGOWE (Genre / User1 / User2).
    Inne filtry (BPM, year, artist, play count…) → None (snapshot crate, nie Smart).
    has tag / genre is → CONTAINS §tag§; contains → zwykły substring.
    """
    cond = (cond or "").strip()
    if not cond:
        return None

    tag_val = _extract_has_tag_value(cond)
    if tag_val is not None:
        v = serato_tag_anchor(tag_val)
        if v:
            return {"field": RULE_FIELD_GENRE, "comparison": CMP_CONTAINS, "value": v}
        return None

    m = _TAG_CONTAINS_RE.search(cond)
    if m:
        v = (m.group(1) or "").strip().lower()
        if v:
            return {"field": RULE_FIELD_GENRE, "comparison": CMP_CONTAINS, "value": v}
        return None

    m = _GENRE_IS_RE.search(cond)
    if m:
        v = serato_tag_anchor(m.group(1))
        if v:
            return {"field": RULE_FIELD_GENRE, "comparison": CMP_CONTAINS, "value": v}
        return None

    return None


def vdj_filter_to_serato_rules(filter_text: str) -> Optional[dict]:
    """
    VDJ filter → Smart Crate TYLKO gdy filtr oparty wyłącznie o tagi
    (User1/User2/Genre has tag|contains|is).
    Inaczej None → zwykły crate ze snapshotem.
    """
    if not filter_text or not filter_text.strip():
        return None
    text = filter_text.strip()
    if "group by" in text.lower():
        return None
    # twardo: cokolwiek poza tagami → nie Smart Crate
    if re.search(
        r"\b(rating|bpm|year|artist|title|song|comment|play\s+count|key\s+difference|bpm\s+difference)\b",
        text,
        re.IGNORECASE,
    ):
        return None

    or_parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    rules: list[dict] = []

    if len(or_parts) > 1:
        for or_part in or_parts:
            and_parts = [
                ap.strip()
                for ap in re.split(r"\s+and\s+", or_part.strip(), flags=re.IGNORECASE)
                if ap.strip()
            ]
            if len(and_parts) != 1:
                return None
            rule = _condition_to_serato_rule(and_parts[0])
            if rule is None:
                return None
            rules.append(rule)
        return {"match_all": False, "rules": rules}

    and_parts = [
        ap.strip()
        for ap in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
        if ap.strip()
    ]
    for cond in and_parts:
        rule = _condition_to_serato_rule(cond)
        if rule is None:
            return None
        rules.append(rule)

    if not rules:
        return None
    return {"match_all": len(rules) > 1, "rules": rules}


def save_serato_smart_crate(
    rules_spec: dict,
    *,
    live_update: bool = True,
) -> bytes:
    """
    Generuje plik .scrate.
    rules_spec: wynik vdj_filter_to_serato_rules (match_all + rules).
    """
    match_all = bool(rules_spec.get("match_all"))
    rules = list(rules_spec.get("rules") or [])
    if not rules:
        raise ValueError("Brak reguł Smart Crate")

    buf = BytesIO()
    _write_rec(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Smart Crate"))
    _write_rec(buf, "rart", _write_bool_nested("rart", match_all))
    _write_rec(buf, "rlut", _write_bool_nested("rlut", live_update))

    # Sortowanie / kolumny — minimalny zestaw jak w Serato
    sort_inner = BytesIO()
    _write_rec(sort_inner, "tvcn", _encode_utf16be("song"))
    _write_rec(sort_inner, "brev", struct.pack("?", False))
    _write_rec(buf, "osrt", sort_inner.getvalue())

    for col in ("song", "artist", "bpm", "key", "genre", "comment"):
        col_inner = BytesIO()
        _write_rec(col_inner, "tvcn", _encode_utf16be(col))
        _write_rec(col_inner, "tvcw", _encode_utf16be("0"))
        _write_rec(buf, "ovct", col_inner.getvalue())

    for rule in rules:
        rbuf = BytesIO()
        _write_rec(rbuf, "trft", _encode_utf16be(str(rule["comparison"])))
        _write_rec(rbuf, "urkt", _write_u32("urkt", int(rule["field"])))
        val = rule["value"]
        if isinstance(val, int):
            _write_rec(rbuf, "urpt", _write_u32("urpt", val))
        else:
            _write_rec(rbuf, "trpt", _encode_utf16be(str(val)))
        _write_rec(buf, "rurt", rbuf.getvalue())

    return buf.getvalue()
