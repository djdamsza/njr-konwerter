# Dopisać aktualizację konwertera do istniejącej wtyczki

Pracuj w repozytorium **ImprezjaBooth**, nie w njr-konwerter i nie w imprezja-www.

Wtyczka: `/Users/test/Documents/ImprezjaBooth/wordpress/njr-booth-konto/`

Program Imprezja Playlist Pro już pyta stronę. Dziś `GET https://nowajakoscrozrywki.pl/api/konwerter/update` nie istnieje. Brak odpowiedzi, błąd albo 404 program traktuje jak „nie ma aktualizacji” i startuje normalnie. Po wdrożeniu ma dostać JSON.

Nie szukaj pliku na GitHubie. Nie podawaj adresu GitHuba. Pliki leżą w tym samym katalogu co instalator fotobudki i quizu: `wp-content/uploads/njr-booth-releases/`.

Wzoruj się na quizie (`njr_quiz_handle_update` w `includes/update.php`), nie na jednym pliku fotobudki. Konwerter ma trzy pliki: Windows, Mac Apple Silicon i Mac Intel. Zasady dla człowieka są jak przy fotobudce: strona `/pobierz` prosi o e-mail i hasło konta, a sam link z JSON-a program ściąga bez logowania.

Nie buduj płatności. Nie ruszaj ścieżek `/api/booth/…` i `/api/quiz/…`. Logowanie konwertera (`/api/konwerter/login` i `/api/konwerter/status`) zostaw.

## Sprawdzenie wersji

`GET https://nowajakoscrozrywki.pl/api/konwerter/update`

Tylko HTTPS. Bez `www`, bez `wp-json`, bez logowania, bez e-maila i bez tokenu. Nagłówek `Cache-Control: no-store`. JSON nie może iść do cache LiteSpeed. Dopisz trasę do `njr_booth_route()`, `njr_booth_dispatch()`, `njr_booth_nocache_api()` i `njr_booth_mark_virtual_page()` tak jak `quiz-update`.

Zły method: **405**.

Gdy brakuje wersji, któregoś pliku albo sumy SHA-256, odpowiedź **404**:

```json
{
  "version": "0.0.0",
  "changelog": "",
  "windows": { "url": "", "sha256": "" },
  "macArm": { "url": "", "sha256": "" },
  "macIntel": { "url": "", "sha256": "" }
}
```

Gdy komplet jest wgrany, **200**:

```json
{
  "version": "1.0.14",
  "changelog": "Co nowego.\nDruga linia też jest pokazana.",
  "windows": {
    "url": "https://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-windows-x64.exe",
    "sha256": "64 znaki hex"
  },
  "macArm": {
    "url": "https://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg",
    "sha256": "64 znaki hex"
  },
  "macIntel": {
    "url": "https://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-macos-intel-x64.dmg",
    "sha256": "64 znaki hex"
  }
}
```

Wersja ma postać `1.0.14` (`njr_booth_version_ok`). Program w polu ma teraz **1.0.13**. Kartę pokazuje tylko przy wyższym numerze. Ten sam numer nic nie pokaże.

Nazwy plików są stałe. Inna nazwa nie przejdzie. W `njr_konwerter_filename_ok` i `njr_konwerter_names` prefix to `Imprezja-Playlist-Pro-`, nie `NJR-konwerter-`.

- Windows: `Imprezja-Playlist-Pro-1.0.14-windows-x64.exe`
- Mac Apple Silicon: `Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg`
- Mac Intel: `Imprezja-Playlist-Pro-1.0.14-macos-intel-x64.dmg`

Numer w nazwie musi być równy polu `version`. Adres zaczyna się od `https://nowajakoscrozrywki.pl/pobierz/`.

## Pobieranie pliku

Dopisz rozpoznanie tych trzech nazw obok `njr_quiz_filename_ok` w `njr_booth_route()` i w `njr_booth_handle_download()`.

`GET https://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg`

Bez logowania, tak jak instalator fotobudki i pliki quizu. Oddawaj tylko plik, który jest aktualnie zapisany przy tej wersji. Inna nazwa: **404**.

Nagłówki: `Content-Type: application/octet-stream`, `Content-Disposition: attachment` z tą nazwą, `Content-Length`, `X-Robots-Tag: noindex, nofollow`.

Przy oddaniu pliku zapisz statystykę jak quiz. W `njr_stats_record` dozwolone produkty to dziś tylko `booth` i `quiz`. Dopisz `konwerter`. Kolumna `product` ma 16 znaków, `konwerter` się mieści. Platformy: `windows`, `macArm`, `macIntel`.

## Strona dla człowieka

Na `https://nowajakoscrozrywki.pl/pobierz`, pod formularzem fotobudki, druga część: „Pobierz Imprezja Playlist Pro”.

Ten sam e-mail i hasło konta (`wp_check_password`, limit 8 prób / 15 minut, te same funkcje `njr_booth_login_limited` i `njr_booth_login_clear`). Po haśle człowiek wybiera Windows, Mac Apple Silicon albo Mac Intel i dostaje ten plik. Bez kompletu trzech plików napis: instalator nie jest jeszcze wgrany.

Sam program nie używa tego formularza. On bierze adres z JSON-a.

## Panel wtyczki

W Ustawieniach → Fotobudka, pod quizem, blok „Aktualizacja Imprezja Playlist Pro”.

Pola:

- wersja, na przykład `1.0.14`
- co nowego (zwykły tekst, do 4000 znaków)
- plik Windows `.exe`
- plik Mac Apple Silicon `.dmg`
- plik Mac Intel `.dmg`

Puste pole zostawia dotychczasowy plik tego systemu. Suma SHA-256 liczy się sama, jak w `njr_quiz_store_file`. Zapis do `njr_booth_settings`:

- `konwerter_update_version`
- `konwerter_update_changelog`
- `konwerter_update_windows_sha`
- `konwerter_update_mac_arm_sha`
- `konwerter_update_mac_intel_sha`

Aktualizacja jest gotowa dopiero, gdy wersja jest poprawna i wszystkie trzy pliki leżą w katalogu wydań z poprawną sumą. Inaczej endpoint zostaje na 404.

Podbij `NJR_BOOTH_VERSION`, jeśli dokładane są nowe opcje, które mają się pojawić na już działającej stronie.

## Sprawdzenie

```bash
curl -sS -D - "https://nowajakoscrozrywki.pl/api/konwerter/update"
```

Zanim pliki wejdą: **404**, `Content-Type` z `application/json`, `"version":"0.0.0"`. Nie strona HTML.

Po wgraniu kompletu 1.0.14: **200**, trzy adresy na `https://nowajakoscrozrywki.pl/pobierz/`, trzy sumy po 64 znaki. Żaden adres nie zawiera `github.com`.

Potem:

```bash
curl -sI "https://nowajakoscrozrywki.pl/pobierz/Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg"
```

Oczekiwane: **200** i `Content-Disposition` z tą nazwą pliku.
