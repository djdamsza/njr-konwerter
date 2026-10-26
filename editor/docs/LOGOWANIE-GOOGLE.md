# Logowanie Google w Imprezja Playlist Pro

Ten opis jest wzorem dla Imprezja Quiz i Imprezja Booth. Konto jest jedno, na stronie. Program nie trzyma hasła. Po Google dostaje ten sam token urządzenia co po e-mailu i haśle.

Wtyczka: `/Users/test/Documents/ImprezjaBooth/wordpress/njr-booth-konto/`, od wersji 1.9.17 (logowanie) i 1.9.18 (saldo na koncie).

## Co robi program

Na ekranie konta jest przycisk **Zaloguj przez Google**. Obok zostaje e-mail i hasło.

1. Program losuje `state` (32 znaki hex) i pamięta go 10 minut.
2. Otwiera przeglądarkę na  
   `https://nowajakoscrozrywki.pl/api/konwerter/google/start?installId=UUID&state=STATE`
3. Co 2 sekundy pyta własny adres `/api/account/google/poll?state=STATE`.
4. Ten adres pyta stronę `GET /api/konwerter/google/result?state=STATE`.
5. Gdy strona odda `deviceToken`, program zapisuje tylko token i e-mail. Hasła nie ma.

`installId` leży na stałe w `~/Library/Application Support/NJR Konwerter/install-id`. Quiz i fotobudka mają własne identyfikatory. Nie wolno ich mieszać.

Kod programu: `editor/njr_account.py` (`google_start`, `google_poll`) i przycisk w `editor/static/index.html`.

## Co robi strona

Trzy adresy, bez `wp-json`:

| Adres | Kto woła | Wynik |
| --- | --- | --- |
| `GET /api/konwerter/google/start` | przeglądarka | przekierowanie do Google |
| `GET /api/konwerter/google/callback` | Google | „Zalogowano. Wróć do programu.” |
| `GET /api/konwerter/google/result?state=` | program | `{"pending":true}` albo ten sam JSON co login |

Callback zamienia kod Google na `id_token`, sprawdza go w `https://oauth2.googleapis.com/tokeninfo` i przyjmuje tylko adres z `email_verified`. Konto WordPress z tym adresem jest używane. Jak go nie ma, strona je zakłada i nie wysyła hasła. Potem `njr_konwerter_pair` przypina `installId` i oddaje `deviceToken`.

Klucze są w WordPressie: **Ustawienia → Fotobudka — konto klienta**.

- Google — identyfikator klienta
- Google — tajny klucz (puste pole przy zapisie zostawia poprzedni)

Adres powrotu, dokładnie, bez `www` i bez ukośnika na końcu:

`https://nowajakoscrozrywki.pl/api/konwerter/google/callback`

## Google Cloud

Projekt: `imprezja-termin`. Klient typu **aplikacja internetowa**, nazwa `Playlist Pro`. Źródła JavaScript puste. W przekierowaniach tylko adres powyżej.

**Odbiorcy:** typ **Z zewnątrz**, stan **W produkcji**. W testowaniu logują się tylko użytkownicy testowi.

**Elementy marki**, zanim publikacja ruszy:

- nazwa: Nowa Jakość Rozrywki
- e-mail pomocy: konto właściciela
- bez logo
- domena: `nowajakoscrozrywki.pl`
- strona: `https://nowajakoscrozrywki.pl/`
- polityka: `https://nowajakoscrozrywki.pl/polityka-prywatnosci/`

Zakresy: `openid`, e-mail, profil. Nic więcej.

Tajny klucz widać raz, przy utworzeniu klienta. Nie wkładaj go do programu ani do repozytorium.

## Quiz i fotobudka

Skopiuj trzy adresy i przycisk. Zamień parowanie na `njr_quiz_pair` albo `njr_booth_pair`. Identyfikator instalacji bierz z tego programu, nie z Playlist Pro.

Ten sam klient Google wystarczy. Każdy program potrzebuje własnego adresu powrotu, dopisanego w tym kliencie, na przykład:

- `https://nowajakoscrozrywki.pl/api/quiz/google/callback`
- `https://nowajakoscrozrywki.pl/api/booth/google/callback`

`state` trzymaj osobno dla każdego programu. Wynik oddawaj raz i kasuj.

## Tokeny

Saldo Playlist Pro jest na koncie (`njr_playlist_tokens`), nie na komputerze. Drugie konto na tej samej instalacji dostaje własne saldo. Zakup, kod i zużycie AI dopisują albo zdejmują tokeny konta, które jest właśnie zalogowane.

Komputery jednego konta mają jedno wspólne saldo. Kod na start zostaje raz na komputer.
