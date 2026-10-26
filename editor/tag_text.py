"""Kandydaci do poprawy tytułu, wykonawcy i albumu oraz braki w tych polach."""
from __future__ import annotations

import json
import re

_GLUED = re.compile(r"[a-ząćęłńóśźż][A-ZĄĆĘŁŃÓŚŹŻ]")
_PUNCT_SPACE = re.compile(r"[a-zA-Z0-9]\.[A-Za-z]")


_BLANK = {
    "", "-", "—", "–", "?", "n/a", "na", "unknown", "unknown artist",
    "nieznany", "brak", "none", "null",
}


_VARIOUS = {
    "various", "various artist", "various artists", "various artis", "various artistes",
    "va", "v a", "v/a",
    "rozni wykonawcy", "różni wykonawcy", "rozni artysci", "różni artyści",
}


def is_various_artist(name: str) -> bool:
    text = " ".join((name or "").replace("/", " ").replace(".", " ").split()).casefold()
    return text in _VARIOUS


def is_blank_tag(value: str) -> bool:
    return (value or "").strip().lower() in _BLANK


def looks_mojibake(value: str) -> bool:
    text = value or ""
    return any(ch in text for ch in "ÃÅÄÂ\ufffd¿³")


def looks_caps(value: str) -> bool:
    text = (value or "").strip()
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 8 and all(ch.isupper() for ch in letters)


def looks_wrong(value: str) -> bool:
    """Ślady dla modelu: złe kodowanie, capslock, brak spacji, zlepione słowa."""
    text = (value or "").strip()
    if looks_mojibake(text) or looks_caps(text):
        return True
    if len(text) < 4:
        return False
    if "  " in value or value != text:
        return True
    if _GLUED.search(text):
        return True
    if _PUNCT_SPACE.search(text):
        return True
    return False


def case_only_change(before: str, after: str) -> bool:
    """Ta sama treść, inna tylko wielkość liter."""
    return (before or "").casefold() == (after or "").casefold()


def is_gap(author: str, title: str) -> bool:
    """Brakuje wykonawcy, tytułu albo obu."""
    return is_blank_tag(author) or is_blank_tag(title)


_SPACED_DASH = re.compile(r"\s+[-–—]\s+")
_JUNK_SIDE = {"topic", "official", "lyrics", "audio", "video", "hd", "4k"}


def is_only_hyphen_name(value: str) -> bool:
    """„IN - GRID” albo „Jay - Z”: to nazwa, nie wykonawca i tytuł."""
    parts = [part.strip() for part in _SPACED_DASH.split((value or "").strip()) if part.strip()]
    if len(parts) != 2:
        return False
    left, right = parts
    if " " in left or " " in right:
        return False
    return len(left) <= 14 and len(right) <= 14


def looks_like_split_candidate(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 5 or _SPACED_DASH.search(text) is None:
        return False
    return not is_only_hyphen_name(text)


def rejects_name_split(before_author: str, before_title: str, author: str, title: str) -> bool:
    """Odrzuca rozbicie In-Grid oraz tytuł, który jest tylko dopiskiem YouTube."""
    if is_only_hyphen_name(before_author) or is_only_hyphen_name(before_title):
        return True
    if (title or "").strip().casefold() in _JUNK_SIDE:
        return True
    left, right = (author or "").strip(), (title or "").strip()
    if left and right and " " not in left and " " not in right and len(left) <= 16 and len(right) <= 16:
        for source in (before_author, before_title):
            compact = re.sub(r"[\s\-–—]+", "", source or "").casefold()
            if compact and compact in {f"{left}{right}".casefold(), f"{right}{left}".casefold()}:
                return True
    old_title = (before_title or "").strip()
    if old_title and _SPACED_DASH.search(old_title) is None:
        new_title = (title or "").strip()
        if new_title.casefold() != old_title.casefold() and old_title.casefold() not in new_title.casefold():
            return True
    return False


_JOINED = re.compile(r"\s[-–—]\s")
_FEAT = re.compile(r"(?i)\b(?:feat|ft|featuring)\.?\b")


def looks_like_joined(title: str, author: str) -> bool:
    """Wykonawca jest pusty, a tytuł wygląda jak „Artysta - utwór” albo ma feat."""
    if not is_blank_tag(author):
        return False
    text = (title or "").strip()
    if len(text) < 8:
        return False
    return _JOINED.search(text) is not None or _FEAT.search(text) is not None


def parse_gap_splits(answer: str) -> list[dict]:
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
        author = str(item.get("author") or "").strip()
        title = str(item.get("title") or "").strip()
        if not author or not title:
            continue
        try:
            idx = int(item.get("idx"))
        except (TypeError, ValueError):
            continue
        out.append({
            "idx": idx,
            "author": author,
            "title": title,
            "why": str(item.get("why") or "").strip(),
        })
    return out


def parse_ai_fixes(answer: str) -> list[dict]:
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
        field = (item.get("field") or "").strip()
        after = str(item.get("after") or "").strip()
        if field not in ("author", "title", "album") or not after:
            continue
        try:
            idx = int(item.get("idx"))
        except (TypeError, ValueError):
            continue
        out.append({
            "idx": idx,
            "field": field,
            "after": after,
            "why": str(item.get("why") or "").strip(),
        })
    return out


def parse_tag_bundle(answer: str) -> tuple[list[dict], list[dict]]:
    """Jedna odpowiedź modelu: poprawki pól i rozdzielone tytuły."""
    text = (answer or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return [], []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return [], []
    if not isinstance(data, dict):
        return [], []
    fixes = parse_ai_fixes(json.dumps(data.get("fixes") or []))
    splits = parse_gap_splits(json.dumps(data.get("splits") or []))
    return fixes, splits
