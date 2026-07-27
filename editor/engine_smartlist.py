"""
Konwersja filter list VDJ → Engine DJ Smartlist (tabela Smartlist w m.db).

Engine 5.x przechowuje reguły jako JSON (kolumna rules), np.:
  {"match":"all","rules":[{"col":"genre","con":"LIKE","param":"'%#rock%'","v":"2.20.0"}],"rv":2}
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

_ENGINE_RULES_VERSION = "2.20.0"
_ENGINE_RULES_RV = 2

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
_RATING_GTE_RE = re.compile(r"rating\s*>=\s*(\d+)", re.IGNORECASE)
_RATING_IS_RE = re.compile(r"rating\s+is\s+(\d+)", re.IGNORECASE)
_PLAY_COUNT_GTE_RE = re.compile(r"play\s+count\s*>=\s*(\d+)", re.IGNORECASE)
_BPM_GTE_RE = re.compile(r"bpm\s*>=\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_BPM_LTE_RE = re.compile(r"bpm\s*<=\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_YEAR_IS_RE = re.compile(r"year\s+is\s+(\d{4})", re.IGNORECASE)
_YEAR_GTE_RE = re.compile(r"year\s*>=\s*(\d{4})", re.IGNORECASE)
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


def _tag_search_value(raw: str) -> str:
    t = raw.strip().lstrip("#")
    return f"#{t}" if t else ""


def _genre_like_rule(search: str) -> dict:
    """Reguła Genre contains — format Engine 5.x (LIKE)."""
    needle = search.strip()
    if not needle:
        return {}
    if not needle.startswith("#") and re.match(r"^[A-Za-z0-9_]+$", needle):
        needle = f"#{needle}"
    esc = needle.replace("'", "''")
    return {
        "col": "genre",
        "con": "LIKE",
        "param": f"'%{esc}%'",
        "v": _ENGINE_RULES_VERSION,
    }


def _condition_to_engine_rule(cond: str) -> Optional[dict]:
    """Pojedynczy warunek VDJ → reguła Engine. None = brak mapowania."""
    cond = cond.strip()
    if not cond:
        return None

    m = _TAG_HAS_RE.search(cond)
    if m:
        v = _tag_search_value(m.group(1))
        if v:
            return _genre_like_rule(v)

    m = _TAG_CONTAINS_RE.search(cond)
    if m:
        val = m.group(1).strip()
        if val:
            return _genre_like_rule(val)

    m = _GENRE_IS_RE.search(cond)
    if m:
        v = _tag_search_value(m.group(1))
        if v:
            return _genre_like_rule(v)

    m = _RATING_GTE_RE.search(cond)
    if m:
        stars = int(m.group(1))
        return {
            "col": "rating",
            "con": ">=",
            "param": "",
            "v": str(max(0, min(100, stars * 20))),
        }

    m = _RATING_IS_RE.search(cond)
    if m:
        stars = int(m.group(1))
        return {
            "col": "rating",
            "con": "=",
            "param": "",
            "v": str(max(0, min(100, stars * 20))),
        }

    m = _PLAY_COUNT_GTE_RE.search(cond)
    if m:
        return {
            "col": "playCount",
            "con": ">=",
            "param": "",
            "v": m.group(1),
        }

    m = _BPM_GTE_RE.search(cond)
    if m:
        return {
            "col": "bpm",
            "con": ">=",
            "param": "",
            "v": str(int(float(m.group(1)))),
        }

    m = _BPM_LTE_RE.search(cond)
    if m:
        return {
            "col": "bpm",
            "con": "<=",
            "param": "",
            "v": str(int(float(m.group(1)))),
        }

    m = _YEAR_IS_RE.search(cond)
    if m:
        return {
            "col": "year",
            "con": "=",
            "param": "",
            "v": m.group(1),
        }

    m = _YEAR_GTE_RE.search(cond)
    if m:
        return {
            "col": "year",
            "con": ">=",
            "param": "",
            "v": m.group(1),
        }

    m = _ARTIST_CONTAINS_RE.search(cond)
    if m:
        val = m.group(1).strip().replace("'", "''")
        if val:
            return {
                "col": "artist",
                "con": "LIKE",
                "param": f"'%{val}%'",
                "v": _ENGINE_RULES_VERSION,
            }

    m = _TITLE_CONTAINS_RE.search(cond)
    if m:
        val = m.group(1).strip().replace("'", "''")
        if val:
            return {
                "col": "title",
                "con": "LIKE",
                "param": f"'%{val}%'",
                "v": _ENGINE_RULES_VERSION,
            }

    m = _COMMENT_CONTAINS_RE.search(cond)
    if m:
        val = m.group(1).strip().replace("'", "''")
        if val:
            return {
                "col": "comment",
                "con": "LIKE",
                "param": f"'%{val}%'",
                "v": _ENGINE_RULES_VERSION,
            }

    return None


def vdj_filter_to_engine_rules(filter_text: str) -> Optional[dict]:
    """
    Konwertuje filtr VDJ na reguły Engine Smartlist.
    Zwraca None gdy filtr jest zbyt złożony (np. mieszane AND/OR, BPM diff, live listy).
    """
    if not filter_text or not filter_text.strip():
        return None
    text = filter_text.strip()
    if "group by" in text.lower():
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
            rule = _condition_to_engine_rule(and_parts[0])
            if rule is None:
                return None
            rules.append(rule)
        return {"match": "one", "rules": rules, "rv": _ENGINE_RULES_RV}

    and_parts = [
        ap.strip()
        for ap in re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
        if ap.strip()
    ]
    for cond in and_parts:
        rule = _condition_to_engine_rule(cond)
        if rule is None:
            return None
        rules.append(rule)

    if not rules:
        return None
    match_mode = "all" if len(rules) > 1 else "one"
    return {"match": match_mode, "rules": rules, "rv": _ENGINE_RULES_RV}


def engine_parent_playlist_path(parts: tuple[str, ...], *, root_name: str = "VDJ") -> str:
    """
    Ścieżka rodzica Smartlisty w formacie Engine (PlaylistPath).
    ('VDJ', 'MyLists', 'gatunki', 'BALLADY') → 'gatunki;MyLists;VDJ;'
    """
    names = list(parts[:-1])
    if names and names[0] == root_name:
        names = names[1:]
    if not names:
        return f"{root_name};"
    chain = list(reversed(names)) + [root_name]
    return ";".join(chain) + ";"


def collect_vdj_smartlists_from_tree(
    playlists: list,
    *,
    root_name: str = "VDJ",
    parent_parts: tuple[str, ...] = (),
) -> list[dict]:
    """Zbiera Smartlisty z drzewa Playlist (filter_text na liście)."""
    out: list[dict] = []
    for pl in playlists or []:
        parts = parent_parts + (pl.name,)
        if getattr(pl, "filter_text", ""):
            rules = vdj_filter_to_engine_rules(pl.filter_text)
            if rules:
                out.append(
                    {
                        "title": pl.name,
                        "parent_playlist_path": engine_parent_playlist_path(
                            parts, root_name=root_name
                        ),
                        "rules": rules,
                    }
                )
        out.extend(
            collect_vdj_smartlists_from_tree(
                getattr(pl, "children", None) or [],
                root_name=root_name,
                parent_parts=parts,
            )
        )
    return out


def _playlist_title_chain(conn: sqlite3.Connection, playlist_id: int) -> tuple[str, ...]:
    """Ścieżka Playlist od roota do liścia, np. ('VDJ', 'MyLists', 'gatunki', 'COVER')."""
    titles: list[str] = []
    cur: int | None = playlist_id
    seen: set[int] = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        row = conn.execute(
            "SELECT title, parentListId FROM Playlist WHERE id = ?",
            (cur,),
        ).fetchone()
        if not row:
            break
        titles.append(row[0] or "")
        cur = row[1]
    return tuple(reversed(titles))


def remove_duplicate_playlist_snapshots_for_smartlists(
    conn: sqlite3.Connection,
    *,
    root_name: str = "VDJ",
) -> dict:
    """
    Usuwa zwykłe Playlist (+ PlaylistEntity), które duplikują Smartlistę
    o tej samej nazwie i parentPlaylistPath (stare snapshoty filtrów VDJ).
    Nie rusza folderów z dziećmi ani list bez odpowiadającej Smartlisty.
    """
    duals = conn.execute(
        """
        SELECT p.id, p.title, p.nextListId,
               (SELECT COUNT(*) FROM Playlist ch WHERE ch.parentListId = p.id) AS child_count
        FROM Playlist p
        WHERE EXISTS (SELECT 1 FROM Smartlist s WHERE s.title = p.title)
        """
    ).fetchall()

    removed_playlists = 0
    removed_entities = 0

    for pid, title, next_list_id, child_count in duals:
        if child_count and child_count > 0:
            continue
        parts = _playlist_title_chain(conn, pid)
        if not parts or parts[-1] != title:
            continue
        expected_parent = engine_parent_playlist_path(parts, root_name=root_name)
        smart = conn.execute(
            """
            SELECT 1 FROM Smartlist
            WHERE title = ? AND parentPlaylistPath = ?
            LIMIT 1
            """,
            (title, expected_parent),
        ).fetchone()
        if not smart:
            continue

        # Utrzymaj łańcuch rodzeństwa nextListId.
        # Najpierw usuń wiersz (UNIQUE parentListId+nextListId), potem przepnij poprzednika.
        prev = conn.execute(
            "SELECT id FROM Playlist WHERE nextListId = ?",
            (pid,),
        ).fetchone()
        ents = conn.execute(
            "DELETE FROM PlaylistEntity WHERE listId = ?",
            (pid,),
        ).rowcount
        conn.execute("DELETE FROM Playlist WHERE id = ?", (pid,))
        if prev:
            conn.execute(
                "UPDATE Playlist SET nextListId = ? WHERE id = ?",
                (next_list_id, prev[0]),
            )
        removed_playlists += 1
        removed_entities += ents

    return {
        "duplicate_playlists_removed": removed_playlists,
        "duplicate_playlist_entities_removed": removed_entities,
    }


def sync_engine_smartlists(
    engine_dir,
    smartlists: list[dict],
    *,
    root_prefix: str = "VDJ",
    replace_vdj: bool = True,
) -> dict:
    """
    Zapisuje Smartlisty do m.db (po merge libdjinterop).
    replace_vdj: usuń istniejące Smartlisty pod drzewem VDJ przed importem.
    Po zapisie usuwa zduplikowane snapshoty Playlist o tych samych nazwach.
    """
    from pathlib import Path

    engine_dir = Path(engine_dir).expanduser().resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"skipped": True, "reason": "no m.db"}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    updated = 0
    removed = 0
    skipped = 0

    conn = sqlite3.connect(str(mdb))
    try:
        if replace_vdj:
            cur = conn.execute(
                "DELETE FROM Smartlist WHERE parentPlaylistPath LIKE ?",
                (f"%;{root_prefix};",),
            )
            removed = cur.rowcount

        by_parent: dict[str, list[dict]] = {}
        for spec in smartlists:
            title = (spec.get("title") or "").strip()
            parent = (spec.get("parent_playlist_path") or "").strip()
            rules = spec.get("rules")
            if not title or not parent or not rules:
                skipped += 1
                continue
            by_parent.setdefault(parent, []).append(spec)

        for parent, items in by_parent.items():
            # Engine wymaga unikalnego (parent, nextPlaylistPath, nextListUuid) — łańcuch rodzeństwa.
            uuids = [str(uuid.uuid4()).upper() for _ in items]
            for idx, spec in enumerate(items):
                title = spec["title"].strip()
                rules_json = json.dumps(
                    spec["rules"], ensure_ascii=False, separators=(",", ": ")
                )
                next_uuid = uuids[idx + 1] if idx + 1 < len(uuids) else ""
                row = conn.execute(
                    "SELECT listUuid FROM Smartlist WHERE title = ? AND parentPlaylistPath = ?",
                    (title, parent),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE Smartlist SET rules = ?, nextListUuid = ?, lastEditTime = ? WHERE listUuid = ?",
                        (rules_json, next_uuid, now, row[0]),
                    )
                    updated += 1
                else:
                    conn.execute(
                        "INSERT INTO Smartlist "
                        "(listUuid, title, parentPlaylistPath, nextPlaylistPath, nextListUuid, rules, lastEditTime) "
                        "VALUES (?, ?, ?, '', ?, ?, ?)",
                        (uuids[idx], title, parent, next_uuid, rules_json, now),
                    )
                    added += 1

        dedupe = remove_duplicate_playlist_snapshots_for_smartlists(
            conn, root_name=root_prefix
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "smartlists_added": added,
        "smartlists_updated": updated,
        "smartlists_removed": removed,
        "smartlists_skipped": skipped,
        **dedupe,
    }
