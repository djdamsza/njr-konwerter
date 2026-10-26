# Dopisać logowanie konwertera do istniejącej wtyczki

Pracuj w repozytorium **ImprezjaBooth**, nie w njr-konwerter i nie w imprezja-www.

Wtyczka już jest na stronie i obsługuje fotobudkę oraz quiz:

`/Users/test/Documents/ImprezjaBooth/wordpress/njr-booth-konto/`

Plik główny: `njr-booth-konto.php`, wersja **1.8.0**. Panel: WordPress → Ustawienia → Fotobudka. Konto klienta jest wspólne (WooCommerce, `https://nowajakoscrozrywki.pl/moje-konto/`). Hasło sprawdza `wp_check_password`.

Konwerter NJR już woła stronę. Dziś `POST https://nowajakoscrozrywki.pl/api/konwerter/login` zwraca **404 HTML**. Program pokazuje wtedy: „Strona nie ma jeszcze wtyczki konwertera”. Po wdrożeniu ma dostać JSON.

Płatności tokenów są opisane osobno w `editor/docs/WTYCZKA-TOKENY.md` w repozytorium njr-konwerter. Ten plik zostaw przy logowaniu i statusie. Nie rób abonamentu miesięcznego konwertera.

## Czego nie ruszać

- Ścieżek `/api/booth/…`, `/api/quiz/…`, `/kup/…` i tabel `njr_booths` oraz `njr_quiz_installs`.
- Salda tokenów fotobudki i licencji quizu. Konwerter ma własną tabelę i własny token urządzenia.
- Haseł, kluczy Stripe i klucza modelu AI. Klucz modelu zostaje na stronie, nie w tej robocie.
- Rejestracji. Klient zakłada konto sam na `/moje-konto/`. Hasło: co najmniej 12 znaków.

Nie używaj `wp-json`. Adresy idą tak jak quiz: mapa w `njr_booth_route()`, obsługa w `njr_booth_dispatch()`.

## Wzorzec

Skopiuj logowanie quizu, nie fotobudki.

Quiz jest w `includes/api.php`: `njr_quiz_handle_login` i `njr_quiz_handle_status`. Parowanie instalacji jest w `includes/store.php`: `njr_quiz_pair`. Quiz dostaje `installId`. Fotobudka dostaje `boothId`. Konwerter też wysyła `installId`, ale to inny program i inna tabela. Ten sam komputer quizu i konwertera to dwa identyfikatory.

## Nowe adresy

Tylko HTTPS.

### Logowanie

`POST https://nowajakoscrozrywki.pl/api/konwerter/login`

`Content-Type: application/json`

```json
{
  "email": "klient@poczta.pl",
  "password": "haslo",
  "installId": "09bbd917-a405-4884-9274-fe7b1fd770a7"
}
```

`installId` to UUID zapisany na stałe w programie: `~/Library/Application Support/NJR Konwerter/install-id`. Powyższy identyfikator jest z Maca właściciela. Nowa instalacja losuje własny. Pusty, za długi albo nie-UUID: **401**, tak jak quiz (`njr_booth_uuid`).

Odpowiedź **200**, JSON, bez strony HTML:

```json
{
  "deviceToken": "64 znaki hex",
  "email": "klient@poczta.pl",
  "tokens": null,
  "subscriptionActive": false,
  "planName": "",
  "subscriptionEndsAt": null
}
```

`deviceToken` jest wymagany przy logowaniu. Program bez niego nie uzna logowania. Token pokaż tylko w tej odpowiedzi. W bazie trzymaj skrót, tym samym sposobem co quiz (`njr_booth_new_token` i `njr_booth_hash_token`). Hasła nie zwracaj.

Złe hasło, instalacja przypisana do innego konta, zły identyfikator albo limit prób: **401** i dokładnie `{"error":"unauthorized"}`. Bez `deviceToken`. Program nie rozróżnia przyczyn.

Limit jest już we wtyczce: 8 nieudanych prób z tego samego IP i e-maila blokuje logowanie na 15 minut (`njr_booth_login_limited`). Użyj tych samych funkcji. Po udanym haśle wywołaj `njr_booth_login_clear`.

Zły method: **405**. Body nie-JSON albo dłuższe niż 4096 znaków: **400** `{"error":"bad_request"}`, jak quiz.

### Stan

`GET https://nowajakoscrozrywki.pl/api/konwerter/status`

Nagłówek: `Authorization: Bearer DEVICE_TOKEN`

Ta sama treść JSON. `deviceToken` w odpowiedzi ma być pustym stringiem. Program zostawia token, który dostał przy logowaniu.

Nieznany albo cofnięty token: **401** `{"error":"unauthorized"}`. Program kasuje zapis i wraca do formularza.

## Zachowanie instalacji

Jedna instalacja należy do jednego konta. Drugie konto z tym samym `installId` dostaje 401 i nie podmienia właściciela.

Jedno konto może mieć kilka instalacji (kilka komputerów). Każda ma własny wiersz i własny token.

Ponowne logowanie tego samego konta na tę samą instalację wystawia nowy token i unieważnia poprzedni (podmiana skrótu, jak `njr_quiz_pair`).

Wylogowanie jest tylko w programie. Strona nie dostaje żądania wylogowania. Konto i przypisanie instalacji zostają.

Pierwsze przypisanie instalacji może wysłać maila w tym samym stylu co quiz (`njr_quiz_mail_paired`), z nazwą programu „NJR Konwerter”. Jak maila nie ma pod ręką, pomiń go. Logowanie ma działać bez maila.

## Tabela

Nowa tabela `{prefix}njr_konwerter_installs`, dokładana w `njr_booth_install()` przez `dbDelta`, obok tabel quizu. Podbij `NJR_BOOTH_VERSION`, żeby `njr_booth_maybe_upgrade()` odpalił instalację na istniejącej stronie.

Kolumny na teraz:

- `id`
- `user_id`
- `install_id` char(36), unikalny
- `first_seen_at`
- `device_token_hash` char(64), unikalny
- `plan_name` varchar(191), domyślnie pusty
- `subscription_ends_at` datetime, null
- `tokens` int, null albo 0

Bez kolumn Stripe. Bez ruszania `njr_stripe_events`.

`subscriptionActive` licz tak: data końca w UTC jest w przyszłości. Puste pola dają `false`, pusty `planName` i `subscriptionEndsAt: null`. `tokens` może być `null`. Program te pola tylko pokaże, gdy przyjdą. Nie blokuje nimi pracy.

## Miejsca w kodzie

W `njr_booth_route()` dopisz:

- `api/konwerter/login` → `konwerter-login`
- `api/konwerter/status` → `konwerter-status`

W `njr_booth_dispatch()` wywołaj nowe handlery. W `njr_booth_nocache_api()` i `njr_booth_mark_virtual_page()` traktuj je jak `quiz-login` i `quiz-status`: JSON, bez cache LiteSpeed, bez strony 404 WordPressa. Każdy błąd też jest JSON-em. HTML albo 404 program czyta jako brak wtyczki.

Handlery mogą być w `includes/api.php` (`njr_konwerter_handle_login`, `njr_konwerter_handle_status`). Zapis w `includes/store.php` (`njr_konwerter_pair`, odczyt po `install_id` i po skrócie tokenu, `njr_konwerter_payload`).

Bearer bierz z `njr_booth_bearer()`.

## Sprawdzenie

Po wdrożeniu, bez zmiany programu:

```bash
curl -sS -D - -X POST "https://nowajakoscrozrywki.pl/api/konwerter/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"biuro@imprezja.pl","password":"ZLE-HASLO","installId":"09bbd917-a405-4884-9274-fe7b1fd770a7"}'
```

Oczekiwane: status **401**, ciało `{"error":"unauthorized"}`, `Content-Type` z `application/json`. Nie strona HTML.

Potem prawdziwe hasło tego konta. Oczekiwane: **200** i `deviceToken`. Drugie logowanie innym kontem z tym samym `installId`: **401**.

`GET /api/konwerter/status` z tym tokenem: **200**, `deviceToken` pusty, ten sam e-mail. Zepsuty token: **401**.

W programie na `http://127.0.0.1:5050` zakładka Logowanie ma przyjąć `biuro@imprezja.pl` i puścić resztę menu. Hasła nie zapisuje. Zostaje `account-session.json` obok `install-id`.
