"""
Tidal OAuth – Authorization Code flow (PKCE).
Oficjalne API Tidal nie obsługuje Device Code – wymaga Authorization Code.
Używa openapi.tidal.com / api.tidalhifi.com z Bearer token.
Wymaga kluczy z developer.tidal.com w ~/.config/njr/tidal-credentials.json
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


def _load_credentials() -> tuple[str, str]:
    """Zwraca (client_id, client_secret). Priorytet: env > plik. Brak domyślnych – wymagane developer.tidal.com."""
    cid = os.environ.get("TIDAL_CLIENT_ID", "").strip()
    csec = os.environ.get("TIDAL_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec
    p = Path.home() / ".config" / "njr" / "tidal-credentials.json"
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            cid = (d.get("client_id") or "").strip()
            csec = (d.get("client_secret") or "").strip()
            if cid and csec:
                return cid, csec
        except Exception:
            pass
    return "", ""


def _get_client_id() -> str:
    return _load_credentials()[0]


def _get_client_secret() -> str:
    return _load_credentials()[1]


def has_tidal_credentials() -> bool:
    """Czy użytkownik ma skonfigurowane klucze Tidal."""
    cid, csec = _load_credentials()
    return bool(cid and csec)


def _token_path() -> Path:
    d = Path.home() / ".config" / "njr"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tidal-token.json"


def _load_token() -> Optional[dict]:
    p = _token_path()
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("accessToken") and data.get("expiresAfter", 0) > time.time() + 60:
            return data
        if data.get("refreshToken"):
            refreshed = _refresh_token(data["refreshToken"])
            if refreshed is not None:
                return refreshed
            return None
    except Exception:
        pass
    return None


def _save_token(access: str, refresh: str, country: str, expires_in: int) -> None:
    with open(_token_path(), "w", encoding="utf-8") as f:
        json.dump({
            "accessToken": access,
            "refreshToken": refresh,
            "countryCode": country,
            "expiresAfter": time.time() + expires_in,
        }, f, indent=2)


def _refresh_token(refresh: str) -> Optional[dict]:
    try:
        cid, csec = _load_credentials()
        if not cid or not csec:
            return None
        data = urllib.parse.urlencode({
            "client_id": cid,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
            "scope": "user.read playlists.read",
        }).encode()
        req = urllib.request.Request(
            "https://auth.tidal.com/v1/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        b64 = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        req.add_header("Authorization", f"Basic {b64}")
        with urllib.request.urlopen(req, timeout=15) as r:
            out = json.loads(r.read().decode())
        if out.get("access_token"):
            _save_token(
                out["access_token"],
                out.get("refresh_token", refresh),
                out.get("user", {}).get("countryCode", "PL"),
                int(out.get("expires_in", 86400)),
            )
            return _load_token()
    except Exception:
        pass
    return None


def _pkce_verifier_challenge() -> tuple[str, str]:
    """Generuje code_verifier i code_challenge (S256)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def get_authorize_url(redirect_uri: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Zwraca (auth_url, state, code_verifier, error).
    User otwiera auth_url w przeglądarce, loguje się, callback otrzyma code.
    code_verifier trzeba zapisać i przekazać do exchange_code_for_token.
    """
    cid, csec = _load_credentials()
    if not cid or not csec:
        return None, None, None, "Brak kluczy Tidal. Utwórz ~/.config/njr/tidal-credentials.json z client_id i client_secret z developer.tidal.com"
    verifier, challenge = _pkce_verifier_challenge()
    state = secrets.token_urlsafe(16)
    # playlists.read wystarczy dla openapi.tidal.com; r_usr usunięty (może być deprecated)
    scope = "user.read playlists.read"
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    url = "https://login.tidal.com/authorize?" + urllib.parse.urlencode(params)
    return url, state, verifier, None


def exchange_code_for_token(code: str, code_verifier: str, redirect_uri: str) -> tuple[bool, Optional[str]]:
    """
    Wymienia authorization code na token. Zwraca (success, error).
    """
    cid, csec = _load_credentials()
    if not cid or not csec:
        return False, "Brak kluczy Tidal"
    try:
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": cid,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "scope": "user.read playlists.read r_usr",
        }).encode()
        req = urllib.request.Request(
            "https://auth.tidal.com/v1/oauth2/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            out = json.loads(r.read().decode())
        if out.get("access_token"):
            user = out.get("user", {}) or {}
            _save_token(
                out["access_token"],
                out.get("refresh_token", ""),
                user.get("countryCode", "PL"),
                int(out.get("expires_in", 86400)),
            )
            return True, None
        return False, out.get("userMessage") or out.get("error_description") or "Brak tokena w odpowiedzi"
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            j = json.loads(body)
            msg = j.get("userMessage") or j.get("error_description") or j.get("error") or body or str(e)
            return False, f"HTTP {e.code}: {msg}"
        except Exception:
            return False, f"HTTP {e.code}: {body or str(e)}"
    except Exception as e:
        return False, str(e)


def get_access_token() -> Optional[str]:
    """Zwraca aktualny access token (z pliku lub po odświeżeniu)."""
    t = _load_token()
    return t.get("accessToken") if t else None


def get_token_data() -> Optional[dict]:
    """Zwraca pełne dane tokena (accessToken, countryCode) lub None."""
    return _load_token()


def fetch_playlist_openapi(playlist_id: str, token: str, country: str = "PL") -> tuple[list[dict], Optional[str]]:
    """
    Pobiera utwory z playlisty przez openapi.tidal.com (oficjalne API v2).
    Działa z tokenem playlists.read (nie wymaga r_usr).
    """
    out: list[dict] = []
    cursor: Optional[str] = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.api+json",
    }
    # Próba 1: include=items,items.artists; przy 404 próba 2: include=items
    last_err: Optional[str] = None
    for include_val in ("items,items.artists", "items"):
        out = []
        cursor = None
        while True:
            try:
                url = f"https://openapi.tidal.com/v2/playlists/{playlist_id}/relationships/items?countryCode={country}&include={include_val}"
                if cursor:
                    url += f"&page[cursor]={urllib.parse.quote(cursor)}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode() if e.fp else ""
                if e.code == 401:
                    return [], "Sesja Tidal wygasła. Połącz ponownie (Połącz z Tidal)."
                if e.code == 404:
                    last_err = "Playlista nie znaleziona (404)."
                    break  # wyjście z while, spróbuj z include=items
                try:
                    j = json.loads(body)
                    return [], j.get("userMessage", body) or f"HTTP {e.code}"
                except Exception:
                    return [], f"HTTP {e.code}: {e.reason}"
            except Exception as e:
                return [], str(e)
            items = data.get("data") or []
            included = {f"{x.get('type')}-{x.get('id')}": x for x in (data.get("included") or [])}
            for it in items:
                tid = it.get("id")
                if not tid:
                    continue
                rid = f"{it.get('type', 'tracks')}-{tid}"
                inc = included.get(rid, {})
                attrs = inc.get("attributes", {}) if isinstance(inc, dict) else {}
                title = attrs.get("title", "") or ""
                dur_raw = attrs.get("duration", 0)
                if isinstance(dur_raw, str) and dur_raw.startswith("PT"):
                    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_raw)
                    duration = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0
                else:
                    duration = int(dur_raw) if isinstance(dur_raw, (int, float)) else 0
                artist = ""
                rels = inc.get("relationships", {}) if isinstance(inc, dict) else {}
                artist_refs = (rels.get("artists") or {}).get("data") or []
                if artist_refs and isinstance(artist_refs[0], dict):
                    arid = artist_refs[0].get("id")
                    art_inc = included.get(f"artists-{arid}", {})
                    artist = (art_inc.get("attributes") or {}).get("name", "") if isinstance(art_inc, dict) else ""
                out.append({
                    "artist": artist or "",
                    "title": title or "",
                    "duration": duration or 0,
                    "source": "tidal",
                    "externalId": str(tid),
                })
            links = data.get("links") or {}
            next_url = links.get("next")
            if not next_url:
                break
            parsed = urllib.parse.urlparse(next_url)
            qs = urllib.parse.parse_qs(parsed.query)
            cursor = (qs.get("page[cursor]") or qs.get("page", {}).get("cursor") or [None])[0]
            if not cursor:
                break
        if last_err and not out:
            continue  # spróbuj z następnym include
        if out:
            return out, None
    return [], last_err or "Playlista nie znaleziona (404)."


def fetch_playlist_tidalhifi(playlist_id: str, token: str, country: str = "PL") -> tuple[list[dict], Optional[str]]:
    """
    Pobiera utwory z playlisty przez api.tidalhifi.com (wymaga r_usr).
    Zwraca (lista {artist, title, duration, source, externalId}, błąd).
    """
    out: list[dict] = []
    offset = 0
    limit = 50
    while True:
        try:
            url = f"https://api.tidalhifi.com/v1/playlists/{playlist_id}/items?countryCode={country}&limit={limit}&offset={offset}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            if e.code == 401:
                return [], "Sesja Tidal wygasła. Połącz ponownie (Połącz z Tidal)."
            if e.code == 404:
                return [], "Playlista nie znaleziona (404)."
            try:
                j = json.loads(body)
                return [], j.get("userMessage", body) or f"HTTP {e.code}"
            except Exception:
                return [], f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return [], str(e)

        items = data.get("items") or []
        for it in items:
            if it.get("type") != "track":
                continue
            track = it.get("item") or it
            tid = track.get("id")
            if not tid:
                continue
            artist = ""
            if "artist" in track:
                a = track["artist"]
                artist = a.get("name", "") if isinstance(a, dict) else str(a)
            elif "artists" in track:
                arts = track["artists"] or []
                if arts and isinstance(arts[0], dict):
                    artist = arts[0].get("name", "")
            duration = track.get("duration") or 0
            if not isinstance(duration, (int, float)):
                duration = 0
            out.append({
                "artist": artist or "",
                "title": track.get("title", "") or "",
                "duration": duration,
                "source": "tidal",
                "externalId": str(tid),
            })
        if len(items) < limit:
            break
        offset += limit
    return out, None
