# Online na Offline – plan funkcji

## Cel

Zamiana playlist online (Tidal, Spotify, YouTube) na playlistę offline z lokalnej kolekcji. Klient przysyła link do playlisty – algorytm dopasowuje utwory z bazy i pozwala użytkownikowi zaakceptować/odrzucić propozycje.

## Przepływ

```
[Link playlisty] → [Pobierz utwory] → [Dopasuj z bazy] → [Przegląd + akceptacja] → [Utwórz playlistę]
```

## Źródła playlist (priorytet)

| Źródło | URL format | API | Uwagi |
|--------|------------|-----|-------|
| **Spotify** | open.spotify.com/playlist/{id} | Client Credentials | Działa – wymaga SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET |
| **YouTube** | youtube.com/playlist?list={id} | Data API v3 | Działa – wymaga YOUTUBE_API_KEY |
| Tidal | tidal.com/playlist/{id} | Nieoficjalne api.tidal.com | Często 404. **Prosty fallback:** [Soundiiz.com](https://soundiiz.com) → Import z URL → wklej link Tidal → Export do tekstu → wklej tutaj |

### Konfiguracja Spotify

1. Zarejestruj aplikację na [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Skopiuj Client ID i Client Secret
3. Ustaw zmienne środowiskowe przed uruchomieniem:
   ```bash
   export SPOTIFY_CLIENT_ID="twoj_client_id"
   export SPOTIFY_CLIENT_SECRET="twoj_client_secret"
   ```

### Konfiguracja YouTube

1. Utwórz projekt w [Google Cloud Console](https://console.cloud.google.com)
2. Włącz **YouTube Data API v3**
3. Utwórz klucz API (Credentials → Create credentials → API key)
4. Ustaw zmienną środowiskową:
   ```bash
   export YOUTUBE_API_KEY="twoj_klucz_api"
   ```
   Uwaga: API ma limit zapytań (quota). Długie playlisty mogą wymagać wielu wywołań.

## Algorytm dopasowania

1. **Dokładne** (bez wątpliwości): Artist + Title + Duration (±2s) – automatyczna akceptacja możliwa
2. **Podejrzane**: Różnice w tytule (remix, feat., live) – wymagana weryfikacja
3. **Propozycje**: Do 5 kandydatów na utwór online, posortowanych po:
   - Zgodność Artist (normalizacja: lowercase, strip)
   - Zgodność Title (similarity)
   - Różnica czasu (mniejsza = lepsza)
   - Opcjonalnie: BPM, Key

## UI (wzór: Duplikaty)

- **Wejście**: Pole na URL playlisty + przycisk „Pobierz i dopasuj”
- **Tabela porównawcza** (każdy wiersz = 1 utwór online):
  - Kolumna **Online**: Artist, Title, Czas, Źródło (Tidal/Spotify/YT), przycisk ▶ (Tidal embed)
  - Kolumna **Propozycje**: Lista kandydatów z bazy – każdy z: Artist, Title, Czas, BPM, ★, Camelot, Listy (w jakich playlistach), przycisk ▶ (odsłuch lokalny)
  - Akcje: **Akceptuj** (wybierz który kandydat) | **Odrzuć** (zostaw puste / pomiń)
- **Podsumowanie**: X dopasowanych, Y do weryfikacji, Z bez dopasowania
- **Wynik**: Przycisk „Utwórz playlistę” – dodaje do kolekcji, tworzy vdjfolder, można edytować nazwę

## API (backend)

| Endpoint | Opis |
|----------|------|
| `POST /api/online-playlist-parse` | Body: `{ url }` → `{ tracks: [{ artist, title, duration, source, externalId }], error? }` |
| `POST /api/online-match` | Body: `{ onlineTracks: [...] }` → `{ matches: [{ onlineIdx, candidates: [{ idx, author, title, duration, bpm, rating, key, playlists, score }] }] }` |
| `POST /api/online-playlist-create` | Body: `{ name, mappings: [{ onlineIdx, acceptedIdx \| null }] }` → tworzy playlistę w bazie |

## Pliki do utworzenia/modyfikacji

- `app.py` – nowe endpointy
- `static/index.html` – nowa zakładka „Online na Offline”, panel, tabela
- `online_playlist_parser.py` (opcjonalnie) – parsowanie URL, fetch Tidal/Spotify/YT
