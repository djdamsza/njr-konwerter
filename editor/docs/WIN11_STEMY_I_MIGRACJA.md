# Win11 — stemy Engine DJ + migracja bibliotek (bez startu od zera)

Przewodnik dla komputera z **Windows 11**, na którym masz to samo konto Cursor i chcesz **kontynuować** pracę z biblioteką DJ (VirtualDJ / Serato / Engine DJ / Rane SYSTEM ONE + dysk Patriot), zwłaszcza **tworzenie stemów** bez Macowego buga z tempami AI.

Repozytorium: [github.com/djdamsza/njr-konwerter](https://github.com/djdamsza/njr-konwerter)  
Wersja aplikacji: plik `VERSION` w korzeniu repo (obecnie linia rozwojowa 1.0.x).

---

## 1. Po co ten dokument

| Cel | Jak |
|-----|-----|
| Nie zaczynać biblioteki od zera | Przenieść **muzykę + Engine Library / Serato / VDJ** (lub synchronizować przez NJR) |
| Robić stemy na Win11 | Engine DJ Desktop na PC — omija Macowy bug tempów CoreML |
| Używać stemów na Rane SYSTEM ONE | Stemy muszą być w `Engine Library/Stems/` na dysku, który widzi kontroler (zwykle Patriot) |
| Trzymać playlisty / cue / tagi | Sync przez **NJR Konwerter**, nie „ślepy” Export to Drive |

---

## 2. Role programów (co jest źródłem prawdy)

```
VirtualDJ  ──┐
Serato DJ  ──┼──►  NJR Konwerter (unified model)  ──►  Engine DJ Desktop (Mac lub Win)
Tidal/offline┘                                              │
                                                            ▼
                                              Dysk Patriot / Rane SYSTEM ONE
                                              (Engine Library + Music + Stems)
```

| Aplikacja | Rola | Typowe dane |
|-----------|------|-------------|
| **VirtualDJ** | Często główna baza tagów, cue, playlist | `database.xml` |
| **Serato DJ** | Alternatywne źródło (crates, Markers2) | `~/Music/_Serato_/` + `database V2` |
| **NJR Konwerter** | Merge / remap / playlisty / stemy (migracja) | Flask UI `http://127.0.0.1:5050` |
| **Engine DJ Desktop** | Biblioteka pod Rane; **Create stems**; analiza | `Music/Engine Library` |
| **Rane SYSTEM ONE** | Odtwarzanie offline z dysku USB/SSD | Czyta `Engine Library` z Patriota |

### Zasady złote (zawsze)

1. **Zamknij** VirtualDJ, Serato DJ i Engine DJ przed sync / merge / migracją stemów w NJR (błąd 409 gdy działają).
2. **NIE używaj** w Sync Manager: **„Export Stems”** przy syncu pojedynczej playlisty — Engine może **usunąć** stemy na dysku Rane, których nie ma w wyeksportowanym zestawie. Użyj migracji NJR („Przenieś na Patriot”).
3. **NIE używaj** **„Export to Drive”**, gdy Patriot **już ma** `Engine Library/Music/` — duplikuje bibliotekę. Playlisty: **„Sync playlisty → Patriot”** w NJR.
4. Stemy to pliki `{trackId} {databaseUuid}.stems` w folderze `Stems/`. Po migracji Mac→Patriot UUID w nazwie może zostać z biblioteki źródłowej; **trackId musi pasować** do utworu na Patriot.

---

## 3. Ścieżki — macOS vs Windows 11

### VirtualDJ

| | macOS | Windows 11 |
|--|-------|------------|
| Baza | `~/Library/Application Support/VirtualDJ/` (często też Documents) | `%USERPROFILE%\Documents\VirtualDJ\` |
| Plik | `database.xml` | `database.xml` |

Przed podmianą `database.xml` zrób kopię (`database.xml.bak`).

### Serato DJ

| | macOS | Windows 11 |
|--|-------|------------|
| Biblioteka | `~/Music/_Serato_/` | `%USERPROFILE%\Music\_Serato_\` |
| Baza | m.in. `database V2` | to samo |
| Serato 4 Library | `~/Library/Application Support/Serato/Library/root.sqlite` | `%APPDATA%\Serato\Library\root.sqlite` |
| Root ścieżek przy eksporcie NJR | `/Users/…/` lub `/Volumes/Dysk/` | `C:\` lub `G:\` (Dysk Google) |

Serato wymaga **ścieżek względnych do roota dysku z literą na Windows** (np. `G:/Mój dysk/muzyka dj/track.mp3`). Samo `Mój dysk/…` sprawia, że Serato szuka pliku na `C:` i nie otwiera go.

**PC backup + Dysk Google:** baza Serato na Win11 ma już aktualne crates/cue, ale ścieżki z Maca (`Users/…/Desktop/…`) nie trafiają w pliki. Muzyka ma **zostać** na Dysku Google (lustrzane / pobrane pliki — ten komputer nie jest głównym). W NJR: **Eksport → Serato DJ → Przepnij ścieżki na Dysk Google**. Nie kopiuje plików. Env `NJR_GOOGLE_DRIVE` albo pole w UI (`G:\Mój dysk`). API: `POST /api/remap-serato-google-drive`. CLI: `python remap_serato_google_drive.py`. Zamknij Serato przed remapem.

### Engine DJ Desktop

| | macOS | Windows 11 |
|--|-------|------------|
| Biblioteka domyślna | `~/Music/Engine Library` | `%USERPROFILE%\Music\Engine Library` |
| Nadpisanie | env `NJR_ENGINE_LIBRARY` | to samo |
| Baza | `Database2/m.db` (+ `hm.db`, `sm.db`, `stm.db`) | to samo |
| Stemy | `Engine Library/Stems/*.stems` | to samo |

### Patriot / Rane (dysk zewnętrzny)

| | macOS | Windows 11 |
|--|-------|------------|
| Typowa ścieżka w kodzie NJR | `/Volumes/Patriot/Engine Library` | **Litera dysku**, np. `E:\Engine Library` lub `F:\Engine Library` |
| Muzyka | `…/Engine Library/Music/` lub poza biblioteką (symlinki) | to samo |

> **Win11 — auto-detekcja:** NJR szuka woluminu o etykiecie **Patriot** oraz folderu `X:\Engine Library\Database2\m.db` (pomija bibliotekę Desktop). Nadpisanie: env `NJR_PATRIOT_ENGINE` albo pole w UI (Eksport → Engine DJ). API: `GET /api/library-paths`. Jeśli litera jest inna niż wykryta — wpisz pełną ścieżkę, np. `F:\Engine Library`.

---

## 4. Co przenosi NJR (mapowanie)

Skrót z `MIGRATION_MODEL.md`:

| Element | VDJ | Serato | Engine |
|---------|-----|--------|--------|
| Ścieżki utworów | FilePath | database V2 + crates | Track.path (często symlinki, bez kopiowania) |
| Tagi / genre | Genre, User1, User2 | tgen | `genre` jako `#tagi` |
| BPM / key | Poi / Tags | plik / V2 | bpm + Camelot |
| Hot cues | Poi cue 1–8 | Markers2 | slot 0–7 |
| Loopy | Poi loop (Size=beaty) | Markers_ 5–12 | max 8 |
| Playlisty | .vdjfolder | .crate | PlaylistEntity |
| Play count | Infos.PlayCount | — | **nie** eksportowane |
| Waveform | — | — | Engine analizuje sam |

API:

- `POST /api/sync-engine-desktop` — VDJ → Engine  
- `POST /api/sync-serato-to-engine` — Serato → Engine  

Szczegóły reguł Engine: `engine_bridge/ENGINE_GUIDELINES.md`.

---

## 5. Start na Win11 (Cursor + NJR) — bez „od zera”

### 5.1 To samo konto Cursor

1. Zaloguj się na Win11 tym samym kontem Cursor co na Macu.
2. Sklonuj repo (nie kopiuj ślepo `.venv` z Maca):

```powershell
cd %USERPROFILE%\Documents
git clone https://github.com/djdamsza/njr-konwerter.git
cd njr-konwerter
```

3. Otwórz folder w Cursor: **File → Open Folder → `njr-konwerter`**.

### 5.2 Python + uruchomienie NJR

```powershell
cd editor
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

Albo: `python app.py` → przeglądarka **http://127.0.0.1:5050**.

W karcie **Eksport → Engine DJ** widać wykryte ścieżki Desktop i Patriota, sync VDJ/Serato oraz workflow stemów (status / partia / migracja).

Binarka (opcjonalnie): `BUILD.md` / `python -m PyInstaller njr.spec` → `NJR-konwerter.exe`.

### 5.3 Engine DJ na Windows

1. Zainstaluj **Engine DJ Desktop** (oficjalny installer Denon/Engine).
2. Pierwsze uruchomienie utworzy `%USERPROFILE%\Music\Engine Library`.
3. Zamknij Engine (pełne wyjście) przed sync z NJR.

### 5.4 Co przenieść z Maca (żeby nie zaczynać od zera)

Wybierz **jeden** wariant główny:

#### A) Muzyka już na Patriotcie (zalecane)

1. Podłącz Patriot do Win11 (zapamiętaj literę, np. `E:`).
2. W Engine DJ / NJR pracuj na bibliotece desktopowej Win, a stemy **migréuj na** `E:\Engine Library`.
3. Jeśli na Patriotcie jest już kompletna `Engine Library` z Mac sync — możesz wskazać ją jako cel stemów; **nie** rób Export to Drive z Maca „jeszcze raz”.

#### B) Serato jako źródło

1. Skopiuj folder `_Serato_` (baza + crates). **Muzyki nie kopiuj** na Desktop — zostaje na Dysku Google (Google Drive for desktop, lustrzane / pobrane).
2. W NJR: **Przepnij ścieżki na Dysk Google** (albo `python remap_serato_google_drive.py`). Ścieżki Mac (`Users/…`) → `Mój dysk/…` / `G:\…`.
3. Na Win ustaw root dysku w eksporcie Serato jeśli robisz nowy eksport (litera `G:\` itd.).
4. NJR: **Sync Serato → Engine** (aplikacje zamknięte).
5. Gdy Patriot podłączony — NJR może dopisać playlisty na dysk (bez Export to Drive).

#### C) VirtualDJ jako źródło

1. Skopiuj `Documents\VirtualDJ\database.xml` (+ ewentualnie folders).
2. Załaduj bazę w NJR → **Sync → Engine Desktop**.
3. Upewnij się, że ścieżki do plików na Win istnieją (ta sama litera dysku / ta sama struktura folderów).

#### D) Sama biblioteka Engine z Maca

Możesz skopiować cały `Engine Library` na Win (`Music\Engine Library`), **ale**:

- ścieżki w `m.db` mogą wskazywać `/Users/...` lub `/Volumes/...` — wtedy utwory będą „brakujące”, dopóki nie zrobisz syncu z lokalnymi plikami / remap;
- bezpieczniej: **muzyka na wspólnym dysku zewnętrznym** + sync NJR na świeżą bibliotekę Win.

---

## 6. Workflow stemów na Win11 (omija bug Maca)

### Dlaczego Windows

Na Macu Engine przy „Create stems” zostawia modele AI w temp (`/var/folders/...`) — [znany bug](https://community.enginedj.com/t/engine-desktop-not-cleaning-temp-files-after-stem-processing-on-mac/60940).  
Na Win11 tego mechanizmu CoreML/APFS nie ma — **ten konkretny pożeracz dysku omijasz**. Nadal potrzebujesz wolnego miejsca na dysku systemowym (temp + wynikowe `.stems`).

### Krok po kroku (UI NJR)

1. Podłącz **Patriot** (litera dysku!).
2. Zamknij Engine / Serato / VDJ.
3. Zsynchronizuj bibliotekę źródłową → Engine Desktop (Serato lub VDJ).
4. W NJR: status stemów / przygotuj playlistę **`NJR / NJR Stems Batch`**.
5. Otwórz **Engine DJ** → playlista batch → **Create stems**.
6. Zamknij Engine.
7. W NJR: **Przenieś stemy na Patriot** (podaj ścieżkę Win, np. `E:\Engine Library`) i usuń lokalne `.stems` z PC, jeśli chcesz zwolnić miejsce.
8. Na imprezie: SYSTEM ONE czyta stemy z Patriota.

### Skrypty (z katalogu `editor/`)

Ścieżki poniżej dostosuj do Win (`--mac` oznacza lokalną bibliotekę Engine Desktop, nawet na PC):

```powershell
# Status
python scripts\migrate_stems_to_patriot.py status --mac "$env:USERPROFILE\Music\Engine Library" --patriot "E:\Engine Library"

# Partia (np. 20 utworów)
python scripts\migrate_stems_to_patriot.py prepare --batch 20 --mac "$env:USERPROFILE\Music\Engine Library" --patriot "E:\Engine Library"

# Po Create stems w Engine:
python scripts\migrate_stems_to_patriot.py migrate --batch 20 --delete-mac --mac "$env:USERPROFILE\Music\Engine Library" --patriot "E:\Engine Library"
```

Pełniejsza pętla: `scripts/auto_stems_to_patriot.py` (na Win używaj `--manual-render`, jeśli automatyczne klikanie UI Engine nie jest dostępne).

Czyszczenie cache Mac (`clean_engine_disk.py`) na Win11 **nie jest potrzebne** do tego buga — to narzędzie pod macOS.

---

## 7. Checklist przed sync / stemami

- [ ] VDJ, Serato, Engine **zamknięte**
- [ ] Patriot podłączony, litera dysku znana
- [ ] Muzyka dostępna pod ścieżkami, które widzi Engine (brak „!” przy plikach)
- [ ] Nie planujesz Export Stems / Export to Drive w Sync Manager
- [ ] Na dysku systemowym Win jest zapas miejsca (zalecane **≥ 20–40 GB** wolnego przy większych partiach)
- [ ] Backup: NJR robi kopię `Database2` przed merge; i tak warto mieć kopię Patriota przed masową migracją

---

## 8. Checklist po pracy

- [ ] Stemy są na Patriot: `…\Engine Library\Stems\`
- [ ] Playlisty na Patriot zaktualizowane przez NJR (nie przez Export to Drive)
- [ ] Test na SYSTEM ONE: załaduj utwór ze stemami
- [ ] Lokalne `.stems` na PC usunięte, jeśli miejsce się kończy
- [ ] Commit / push zmian w repo NJR tylko jeśli zmieniałeś kod — dane biblioteki **nie** idą do Gita

---

## 9. Typowe problemy

| Objaw | Przyczyna | Co zrobić |
|-------|-----------|-----------|
| Sync 409 / „aplikacja uruchomiona” | VDJ/Serato/Engine w tle | Zamknij procesy w Menedżerze zadań |
| Brakujące pliki po przeniesieniu na Win | Ścieżki Mac w bazie | **Przepnij ścieżki na Dysk Google** (Serato) albo wspólny dysk + sync NJR; nie kopiuj ślepo samego `m.db` |
| Serato szuka plików na Desktop / Users/Mac | Baza z Maca, muzyka na GDrive | NJR remap GDrive; nie kopiuj muzyki na ten PC (backup) |
| Stemy znikają z Patriota | Export Stems w Sync Manager | Tylko migracja NJR |
| Podwójna biblioteka na Patriot | Export to Drive | Diagnostyka `GET /api/diagnose-patriot-library`; naprawa przed kolejnym sync |
| Create stems niedostępne | Brak/niepełne info utworu | W Engine: **Re-import track info** (wcześniej potwierdzone na Macu) |
| Analiza / waveform nie idzie | Uprawnienia / dysk | Sprawdź dostęp Engine do folderu muzyki; antivirus nie blokuje |
| NJR nie widzi Patriota | Ścieżka `/Volumes/Patriot` | Podaj `E:\Engine Library` (litera z Eksploratora) |
| Duplikaty playlist po sync | Orphan PE / stare ID | Post-merge repair w NJR; „Sync playlisty → Patriot” |

---

## 10. Powiązane pliki w repo

| Plik | Temat |
|------|--------|
| `editor/MIGRATION_MODEL.md` | Co idzie VDJ/Serato → Engine |
| `editor/engine_bridge/ENGINE_GUIDELINES.md` | Reguły merge Engine / Serato |
| `editor/docs/EKSPORT_TAGOW_INSTRUKCJA.md` | ID3, root dysku Serato |
| `editor/docs/VDJ_RB_MIGRACJA.md` | VDJ → Rekordbox (osobny tor) |
| `editor/docs/ONLINE_NA_OFFLINE.md` | Tidal/Spotify → lokalne |
| `editor/engine_stems.py` | Logika stemów + ostrzeżenia Sync Manager |
| `editor/scripts/migrate_stems_to_patriot.py` | CLI partii stemów |
| `editor/engine_disk_cleanup.py` | Cache AI **tylko macOS** |
| `editor/docs/WIN11_STEMY_I_MIGRACJA.md` | Ten przewodnik: Win11, stemy, Patriot |
| `editor/library_paths.py` | Auto-detekcja Patriota / VDJ / Serato / Dysku Google (Win vs Mac) |
| `editor/serato_gdrive.py` | Remap ścieżek Serato → pliki na Dysku Google (bez kopiowania) |
| `editor/remap_serato_google_drive.py` | CLI remap Serato → GDrive |

---

## 11. Minimalna sesja „stemy na Win11 dziś”

1. Clone `njr-konwerter` + `pip install` + `python launcher.py`  
2. Podłącz Patriot → zapisz literę (`E:`)  
3. Sync Serato lub VDJ → Engine (aplikacje zamknięte)  
4. `prepare` batch → Engine **Create stems** → `migrate` na `E:\Engine Library`  
5. Test na SYSTEM ONE  

Nie kopiuj `.venv` z Maca. Nie rób Export to Drive. Nie rób Export Stems w Sync Manager.
