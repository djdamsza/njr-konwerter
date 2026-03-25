"""
Parser playlist online (Tidal, Spotify, YouTube) oraz ręczna lista.
- Tidal: nieoficjalne api.tidal.com (token urządzenia) – playlisty często 404.
- Spotify: Client Credentials (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET) – publiczne playlisty.
- YouTube: Data API v3 (YOUTUBE_API_KEY) – playlistItems.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

TIDAL_HEADERS = {
    "User-Agent": "VirtualDJ-Editor/1.0",
    "x-tidal-token": "gsFXkJqGrUNoYMQPZe4k3WKwijnrp8iGSwn3bApe",
}


def _extract_tidal_playlist_id(url: str) -> Optional[str]:
    """Wyciąga ID playlisty z URL Tidal. tidal.com/browse/playlist/{id}"""
    if not url or not url.strip():
        return None
    url = url.strip()
    # tidal.com/browse/playlist/xxx, listen.tidal.com/playlist/xxx, tidal.com/playlist/xxx
    for pattern in [
        r"tidal\.com/browse/playlist/([a-zA-Z0-9\-]+)",
        r"listen\.tidal\.com/playlist/([a-zA-Z0-9\-]+)",
        r"tidal\.com/playlist/([a-zA-Z0-9\-]+)",
        r"tidal\.com/.*playlist[/=]([a-zA-Z0-9\-]+)",
    ]:
        m = re.search(pattern, url, re.I)
        if m:
            return m.group(1).strip()
    return None


def _parse_tidal_track(t: dict) -> Optional[dict]:
    """Wyciąga dane utworu z obiektu Tidal API."""
    track = t.get("item") if isinstance(t.get("item"), dict) else t
    if not track and isinstance(t, dict):
        track = t
    if not track:
        return None
    tid = track.get("id")
    if not tid:
        return None
    artist = ""
    if "artist" in track:
        a = track["artist"]
        artist = a.get("name", "") if isinstance(a, dict) else str(a)
    elif "artists" in track:
        artists = track["artists"] or []
        if artists:
            a = artists[0] if isinstance(artists[0], dict) else {}
            artist = a.get("name", "") if isinstance(a, dict) else str(artists[0])
    duration = track.get("duration") or 0
    if not isinstance(duration, (int, float)):
        duration = 0
    return {
        "artist": artist or "",
        "title": track.get("title", "") or "",
        "duration": duration,
        "source": "tidal",
        "externalId": str(tid),
    }


def fetch_tidal_playlist(playlist_id: str, country: str = "PL") -> tuple[list[dict], Optional[str]]:
    """
    Pobiera utwory z playlisty Tidal.
    Najpierw próbuje api.tidalhifi.com (OAuth token), potem api.tidal.com (fallback).
    Zwraca (lista {artist, title, duration, source, externalId}, błąd lub None).
    """
    try:
        from tidal_auth import get_token_data, fetch_playlist_openapi, fetch_playlist_tidalhifi
        t = get_token_data()
        if t and t.get("accessToken"):
            token = t["accessToken"]
            country_code = t.get("countryCode") or country
            for fetch_fn in (fetch_playlist_openapi, fetch_playlist_tidalhifi):
                tracks, err = fetch_fn(playlist_id, token, country_code)
                if tracks:
                    return tracks, None
                if err and "404" not in (err or ""):
                    return [], err
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: api.tidal.com (x-tidal-token) – czasem działa dla publicznych playlist gdy OAuth 404
    out: list[dict] = []
    json_mod = __import__("json")
    last_err: Optional[str] = None
    for endpoint in ("tracks", "items"):
        try:
            url = f"https://api.tidal.com/v1/playlists/{playlist_id}/{endpoint}?countryCode={country}&limit=500"
            req = urllib.request.Request(url, headers=TIDAL_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json_mod.loads(r.read().decode())
            items = data.get("items") or data.get("tracks") or []
            for t in items:
                parsed = _parse_tidal_track(t)
                if parsed:
                    out.append(parsed)
            if out:
                return out, None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                last_err = (
                    "Tidal API nie zwraca playlist (404). Kliknij „Połącz z Tidal” w panelu Online na Offline, wpisz kod na stronie Tidal, potem spróbuj ponownie. "
                    "Alternatywa: Soundiiz.com → Import z URL → Export do tekstu. Lub wklej listę ręcznie: Artist - Title."
                )
            elif e.code == 400:
                last_err = (
                    "Tidal API odrzucił żądanie (400). Kliknij „Połącz z Tidal” w panelu Online na Offline, wpisz kod na stronie Tidal, potem spróbuj ponownie. "
                    "Alternatywa: Soundiiz.com → Import z URL → Export do tekstu. Lub wklej listę ręcznie: Artist - Title."
                )
            else:
                last_err = f"Tidal API HTTP {e.code}: {e.reason}"
            continue
        except urllib.error.URLError as e:
            last_err = f"Brak połączenia: {e.reason}"
            continue
        except Exception as e:
            last_err = f"Błąd: {type(e).__name__}: {e}"
            continue
    return [], last_err or "Nie udało się pobrać playlisty Tidal."


def _extract_spotify_playlist_id(url: str) -> Optional[str]:
    """Wyciąga ID playlisty z URL Spotify. open.spotify.com/playlist/{id}"""
    if not url or not url.strip():
        return None
    url = url.strip()
    for pattern in [
        r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)",
        r"spotify\.com/playlist/([a-zA-Z0-9]+)",
    ]:
        m = re.search(pattern, url, re.I)
        if m:
            return m.group(1).strip()
    return None


def _spotify_get_token() -> Optional[str]:
    """Client Credentials flow – zwraca access token lub None."""
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    try:
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        return data.get("access_token")
    except Exception:
        return None


def fetch_spotify_playlist(playlist_id: str) -> tuple[list[dict], Optional[str]]:
    """
    Pobiera utwory z publicznej playlisty Spotify (Client Credentials).
    Zwraca (lista {artist, title, duration, source, externalId}, błąd lub None).
    Wymaga SPOTIFY_CLIENT_ID i SPOTIFY_CLIENT_SECRET w zmiennych środowiskowych.
    """
    token = _spotify_get_token()
    if not token:
        return [], (
            "Brak SPOTIFY_CLIENT_ID lub SPOTIFY_CLIENT_SECRET. "
            "Zarejestruj aplikację na developers.spotify.com i ustaw zmienne środowiskowe."
        )
    out: list[dict] = []
    offset = 0
    limit = 100
    while True:
        try:
            url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit={limit}&offset={offset}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return [], "Nieprawidłowe Spotify Client ID/Secret."
            if e.code == 404:
                return [], "Playlista Spotify nie znaleziona (404)."
            return [], f"Spotify API HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return [], f"Brak połączenia: {e.reason}"
        except Exception as e:
            return [], f"Błąd: {type(e).__name__}: {e}"

        items = data.get("items") or []
        for it in items:
            track = it.get("track")
            if not track or not isinstance(track, dict):
                continue
            tid = track.get("id")
            if not tid:
                continue
            artists = track.get("artists") or []
            artist = ""
            if artists and isinstance(artists[0], dict):
                artist = artists[0].get("name", "") or ""
            duration_ms = track.get("duration_ms") or 0
            duration = int(duration_ms) // 1000 if duration_ms else 0
            out.append({
                "artist": artist,
                "title": track.get("name", "") or track.get("title", "") or "",
                "duration": duration,
                "source": "spotify",
                "externalId": str(tid),
            })
        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
    return out, None


def _extract_youtube_playlist_id(url: str) -> Optional[str]:
    """Wyciąga ID playlisty z URL YouTube. youtube.com/playlist?list={id}"""
    if not url or not url.strip():
        return None
    url = url.strip()
    for pattern in [
        r"youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)",
        r"youtu\.be/.*[?&]list=([a-zA-Z0-9_-]+)",
    ]:
        m = re.search(pattern, url, re.I)
        if m:
            return m.group(1).strip()
    return None


def fetch_youtube_playlist(playlist_id: str) -> tuple[list[dict], Optional[str]]:
    """
    Pobiera utwory z playlisty YouTube (Data API v3).
    Zwraca (lista {artist, title, duration, source, externalId}, błąd lub None).
    Wymaga YOUTUBE_API_KEY w zmiennych środowiskowych.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return [], (
            "Brak YOUTUBE_API_KEY. Uzyskaj klucz w Google Cloud Console (YouTube Data API v3) i ustaw zmienną środowiskową."
        )
    out: list[dict] = []
    page_token: Optional[str] = None
    while True:
        try:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            qs = urllib.parse.urlencode(params)
            req_url = f"https://www.googleapis.com/youtube/v3/playlistItems?{qs}"
            req = urllib.request.Request(req_url)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                body = e.read().decode() if e.fp else ""
                if "quotaExceeded" in body or "quota" in body.lower():
                    return [], "YouTube API: przekroczono limit zapytań (quota). Spróbuj później."
                return [], "YouTube API 403: brak dostępu. Sprawdź YOUTUBE_API_KEY i włącz YouTube Data API v3."
            if e.code == 404:
                return [], "Playlista YouTube nie znaleziona (404)."
            return [], f"YouTube API HTTP {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return [], f"Brak połączenia: {e.reason}"
        except Exception as e:
            return [], f"Błąd: {type(e).__name__}: {e}"

        items = data.get("items") or []
        for it in items:
            snippet = it.get("snippet") or {}
            content = it.get("contentDetails") or {}
            vid = content.get("videoId")
            if not vid:
                continue
            title = snippet.get("title", "") or ""
            channel = snippet.get("videoOwnerChannelTitle", "") or snippet.get("channelTitle", "") or ""
            # Często tytuł ma format "Artist - Title" lub "Artist – Title"
            parts = re.split(r"\s*[\-–—]\s*", title, maxsplit=1)
            if len(parts) >= 2 and (parts[0].strip() and parts[1].strip()):
                artist, track_title = parts[0].strip(), parts[1].strip()
            else:
                artist, track_title = channel, title
            out.append({
                "artist": artist,
                "title": track_title,
                "duration": 0,
                "source": "youtube",
                "externalId": vid,
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out, None


def parse_manual_list(text: str) -> list[dict]:
    """
    Parsuje ręcznie wklejoną listę. Obsługuje:
    - Artist - Title (po jednym w linii)
    - 1. Artist - Title 3:45 (z numerem i czasem)
    - Artist – Title · 3:45 (z middle dot)
    """
    out = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Usuń numer na początku: "1. " lub "01. "
        line = re.sub(r"^\d+\.\s*", "", line)
        # Usuń czas na końcu: " 3:45" lub " · 3:45"
        line = re.sub(r"\s*[·•]\s*\d+:\d{2}\s*$", "", line)
        line = re.sub(r"\s+\d+:\d{2}\s*$", "", line)
        line = line.strip()
        if not line:
            continue
        # Artist - Title lub Artist – Title (en dash)
        parts = re.split(r"\s*[\-–—]\s*", line, maxsplit=1)
        artist = (parts[0] or "").strip()
        title = (parts[1] or "").strip() if len(parts) > 1 else ""
        if artist or title:
            out.append({
                "artist": artist,
                "title": title,
                "duration": 0,
                "source": "manual",
                "externalId": "",
            })
    return out


def parse_playlist_url(url: str) -> tuple[list[dict], Optional[str], str]:
    """
    Parsuje URL lub tekst. Zwraca (tracks, error, source).
    source: 'tidal' | 'spotify' | 'manual'
    """
    url = (url or "").strip()
    if not url:
        return [], "Wklej URL playlisty (Tidal, Spotify) lub listę utworów (Artist - Title).", ""

    # Spotify URL (wymaga SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET)
    spotify_id = _extract_spotify_playlist_id(url)
    if spotify_id:
        tracks, err = fetch_spotify_playlist(spotify_id)
        return tracks, err, "spotify"

    # Tidal URL
    tidal_id = _extract_tidal_playlist_id(url)
    if tidal_id:
        tracks, err = fetch_tidal_playlist(tidal_id)
        return tracks, err, "tidal"

    # Może to być ręczna lista (wiele linii)
    if "\n" in url or (" - " in url and ("tidal" not in url.lower() and "spotify" not in url.lower() and "youtube" not in url.lower())):
        tracks = parse_manual_list(url)
        if tracks:
            return tracks, None, "manual"
        return [], "Nie rozpoznano formatu. Użyj: Artist - Title (po jednym w linii).", ""

    # YouTube URL (wymaga YOUTUBE_API_KEY)
    youtube_id = _extract_youtube_playlist_id(url)
    if youtube_id:
        tracks, err = fetch_youtube_playlist(youtube_id)
        return tracks, err, "youtube"

    return [], "Nieobsługiwany URL. Obsługiwane: Spotify, Tidal, YouTube. Lub wklej listę: Artist - Title.", ""
