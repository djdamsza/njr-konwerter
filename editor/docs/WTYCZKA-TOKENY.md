# Tokeny AI Imprezja Playlist Pro — Stripe we wtyczce

Pracuj w repozytorium **ImprezjaBooth**, we wtyczce `wordpress/njr-booth-konto/`. Nie w njr-konwerter i nie w imprezja-www.

Program **1.0.14** już woła zakup i zużycie. Tokenów nie trzyma u siebie. Stan bierze z konta na `https://nowajakoscrozrywki.pl`. To osobne saldo od tokenów fotobudki i od licencji quizu. Tabela: `{prefix}njr_konwerter_installs`, kolumna `tokens` (dziś `NULL` = brak tokenów).

Zakup ma działać w dwóch miejscach i kończyć się tą samą sesją Stripe:

1. Konto na stronie: `https://nowajakoscrozrywki.pl/moje-konto/` oraz sklep `/kup/tokeny?install=UUID`.
2. Aplikacja Imprezja Playlist Pro: `POST /api/konwerter/checkout`.

Klucz Stripe zostaje w ustawieniach wtyczki (`stripe_secret`, `stripe_webhook_secret`). Nie wkładaj go do programu ani do gita.

Darmowa wersja programu działa bez tokenów. AI staje, gdy `tokens` jest puste, `null` albo mniejsze niż koszt.

## Paczki

Tylko te trzy. Kwoty w groszach, waluta PLN. Nie bierz ich z ustawień fotobudki (`njr_booth_token_packs` to inne ceny).

| id | tokeny | cena | grosze |
| --- | --- | --- | --- |
| `10` | 10 | 6 zł | 600 |
| `50` | 50 | 25 zł | 2500 |
| `100` | 100 | 40 zł | 4000 |

Inny `pack`: **400** `{"error":"bad_request"}`.

Tokeny dopisuj do wiersza instalacji (`install_id`), nie do użytkownika i nie do `njr_booths`. Jedno konto może mieć kilka instalacji. Zakup zasila tylko tę, którą klient wybrał. Program widzi saldo swojej instalacji.

## Jedna funkcja sesji

Nowa funkcja, obok `njr_quiz_stripe_checkout` w `includes/stripe.php`. Nie rozszerzaj `njr_booth_stripe_checkout` — ta wymaga `booth_id`.

`njr_konwerter_stripe_checkout(int $user_id, array $install, string $pack): string|WP_Error`

- instalacja należy do `$user_id` (`njr_konwerter_get_by_install_id`, potem porównanie `user_id`)
- `pack` jest jednym z `10` / `50` / `100`
- `mode` = `payment`
- `currency` = `pln`
- `unit_amount` = grosze z tabeli
- nazwa: `Imprezja Playlist Pro — 50 tokenów` (z właściwą liczbą)
- `customer_email` z konta WordPress
- `success_url`: `https://nowajakoscrozrywki.pl/kup/dziekujemy?session_id={CHECKOUT_SESSION_ID}`
- `cancel_url`: `https://nowajakoscrozrywki.pl/kup/tokeny?install=INSTALL_ID`
- metadane:
  - `product` = `konwerter`
  - `kind` = `konwerter_tokens`
  - `user_id`
  - `install_id` — UUID tej instalacji
  - `tokens` — `10`, `50` albo `100`
  - `pack` — to samo

Nie dodawaj tokenów w tej funkcji. Dopiero webhook po opłaceniu.

Strona i program wołają tę samą funkcję.

## Zakup z programu

`POST https://nowajakoscrozrywki.pl/api/konwerter/checkout`

Nagłówek: `Authorization: Bearer DEVICE_TOKEN`

```json
{ "pack": "50" }
```

**200:**

```json
{ "url": "https://checkout.stripe.com/c/pay/..." }
```

Program otwiera tylko adres zaczynający się od `https://checkout.stripe.com/` albo `https://nowajakoscrozrywki.pl/`.

Token nieznany: **401** `{"error":"unauthorized"}`. Zły `pack` albo body nie-JSON: **400**. Stripe nie odpowiedział: **502** `{"error":"stripe"}`.

Dopisz w `njr_booth_route()`:

- `api/konwerter/checkout` → `konwerter-checkout`
- `api/konwerter/spend` → `konwerter-spend`

W `njr_booth_dispatch()`, `njr_booth_nocache_api()` i `njr_booth_mark_virtual_page()` traktuj oba jak `spend` fotobudki: JSON, bez cache. Dziś tych dwóch ścieżek nie ma, więc żywa strona oddaje **404 HTML**.

## Zakup na koncie

W `njr_booth_render_account_body` (`includes/account.php`), za kartą quizu, dodaj kartę **Imprezja Playlist Pro**. Wzorzec to `njr_quiz_render_account_card`.

- brak instalacji: napis „W Imprezja Playlist Pro zaloguj się tym samym e-mailem i hasłem. Potem wróć tutaj i kup tokeny.”
- jest instalacja: tabela z krótką nazwą instalacji i liczbą tokenów (`NULL` pokazuj jako 0)
- przy każdej instalacji przycisk „Kup tokeny” na `/kup/tokeny?install=INSTALL_ID`
- w zdaniu o wspólnym koncie dopisz Imprezja Playlist Pro obok fotobudki i quizu

`/kup/tokeny` zostaje sklepem fotobudki, gdy w adresie nie ma `install`. Gdy jest `install=` z UUID konwertera:

- niezalogowany: przekierowanie na logowanie WordPress i powrót na ten sam adres (tak robi `njr_booth_render_shop`)
- UUID nie należy do zalogowanego: komunikat, bez sesji Stripe
- należy: trzy paczki obok siebie (liczba, pod nią „tokenów”, pod tym cena) i przycisk, który woła `njr_konwerter_stripe_checkout` i robi `wp_redirect` na adres Stripe
- formularz z nonce, jak `njr_booth_shop_post`
- parametr `pack` w adresie może zaznaczyć paczkę, ale i tak klient klika sam

Po płatności `/kup/dziekujemy` zostaje. W tekście dopisz, że tokeny Playlist Pro też czekają na potwierdzenie Stripe. Link „Wróć do programów” już jest i ma pokazać nowy stan na karcie.

## Webhook

W `njr_booth_apply_checkout_session`, **przed** szukaniem fotobudki (`njr_booth_booth_from_meta`), gałąź:

`product === konwerter` albo `kind === konwerter_tokens`.

Gdy `payment_status` jest `paid` (albo zdarzenie `checkout.session.async_payment_succeeded` i status opłacony):

- `tokens` z metadanych musi być 10, 50 albo 100
- `install_id` musi być UUID wiersza, którego `user_id` zgadza się z metadanymi
- `njr_booth_claim_event('konwerter-tokens:' . session_id)` — drugi raz tej samej sesji nic nie dodaje
- potem jedna aktualizacja:

```sql
UPDATE {prefix}njr_konwerter_installs
SET tokens = COALESCE(tokens, 0) + %d
WHERE install_id = %s AND user_id = %d
```

Zły `install_id`, obce `user_id` albo obce `tokens`: nic nie dopisuj. Zdarzenie i tak jest już zajęte przez `njr_booth_claim_event` na początku webhooka, więc Stripe nie będzie go powtarzał w nieskończoność.

To nie jest abonament. Nie ustawiaj `subscription_ends_at`. Nie ruszaj `njr_booths` ani `njr_quiz_installs`.

## Zużycie

`POST https://nowajakoscrozrywki.pl/api/konwerter/spend`

Ten sam Bearer.

```json
{ "count": 1 }
```

`count` to liczba całkowita od 1 do 30. Poza tym: **400**.

Token nieznany: **401** `{"error":"unauthorized"}`.

`NULL` traktuj jak 0. Stan mniejszy niż `count`: **409** `{"error":"no_tokens","tokens":0}`. Nic nie odejmuj.

Gdy stanu starcza, jedna aktualizacja, która nie zejdzie poniżej zera:

```sql
UPDATE {prefix}njr_konwerter_installs
SET tokens = tokens - %d
WHERE install_id = %s AND COALESCE(tokens, 0) >= %d
```

Zero zmienionych wierszy: **409**, bez ponownego odejmowania. Gdy wiersz się zmienił: **200** i ten sam JSON co `GET /api/konwerter/status` (`njr_konwerter_payload`). `deviceToken` pusty. `tokens` to stan **po** odjęciu, liczba, nie `null`.

## Sprawdzenie

Program ma być zalogowany. Instalacja właściciela na tym Macu: `09bbd917-a405-4884-9274-fe7b1fd770a7`.

Na koncie, po zalogowaniu na stronie, karta Imprezja Playlist Pro pokazuje 0 i prowadzi do trzech paczek. Klik otwiera `checkout.stripe.com`.

Z programu ten sam zakup:

```bash
curl -sS -D - -X POST "https://nowajakoscrozrywki.pl/api/konwerter/checkout" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pack":"10"}'
```

Oczekiwane: **200** i `url` na `checkout.stripe.com`. Po testowej płatności webhook dopisuje 10 do tego wiersza. `GET /api/konwerter/status` pokazuje `tokens` większe o 10. Karta na `/moje-konto/` pokazuje to samo.

Zużycie:

```bash
curl -sS -D - -X POST "https://nowajakoscrozrywki.pl/api/konwerter/spend" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"count":1}'
```

Oczekiwane: **200**, `tokens` o 1 mniejsze. Przy stanie 0: **409** i stan zostaje 0. Saldo fotobudki się nie zmienia.
