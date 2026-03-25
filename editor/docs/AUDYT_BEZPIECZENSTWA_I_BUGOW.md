# Audyt konwertera NJR – błędy, podatności i ryzyka

**Data:** 2025-03-13  
**Zakres:** `tools/vdj-database-editor` – serwer Flask, frontend, licencjonowanie  
**Status:** Naprawy krytyczne i średnie – wprowadzone 2025-03-13

---

## Krytyczne – mogą sparaliżować pracę lub użytkownika

### 1. CORS – dostęp z dowolnej strony

**Lokalizacja:** `app.py` linia 72: `CORS(app)` bez parametrów

**Problem:** Flask-CORS domyślnie zezwala na zapytania z **dowolnej domeny**. Jeśli użytkownik ma otwarty konwerter (localhost:5050) i odwiedzi złośliwą stronę, ta strona może:
- wysyłać żądania do API konwertera,
- np. wywołać `/api/delete-files` z dowolnymi ścieżkami i **usunąć pliki użytkownika**.

**Rekomendacja:**
```python
CORS(app, origins=['http://127.0.0.1:5050', 'http://localhost:5050', 'http://127.0.0.1:5051', ...])
```
 albo ograniczyć do `127.0.0.1` i `localhost` z rozsądnym zakresem portów (np. 5050–5060).

---

### 2. Brak walidacji ścieżek – path traversal i usuwanie dowolnych plików

**Lokalizacje:**
- `/api/delete-files` (POST) – linia 2590
- `/api/orphan-file` (DELETE) – linia 5151
- `/api/todo-save` (POST) – linia 2665 (zapis do podanego katalogu)
- `/api/open-folder` (POST) – linia 5112
- `/api/load`, `/api/save` – ścieżki od użytkownika

**Problem:** Ścieżki z requestu są używane bez sprawdzenia, czy:
- wychodzą poza katalog użytkownika (np. `/etc/passwd`, `C:\Windows\System32`),
- wskazują na pliki systemowe,
- są w ogóle „dozwolone” (np. tylko w katalogu muzyki użytkownika).

**Przykład ataku (przy otwartym CORS):**
```javascript
fetch('http://127.0.0.1:5050/api/delete-files', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({paths: ['/Users/test/Documents/projekt.docx']})
})
```

**Rekomendacja:**
- Dla `/api/delete-files`: weryfikować, że ścieżka jest w katalogu „znanym” z bazy (np. katalog nadrzędny załadowanych utworów) lub w wybranym przez użytkownika katalogu roboczym.
- Wprowadzić funkcję `_is_path_safe(path: Path, allowed_roots: list[Path]) -> bool` i używać jej wszędzie, gdzie ścieżka pochodzi od użytkownika.

---

### 3. `api/orphan-file` (DELETE) – możliwość usunięcia dowolnego pliku audio

**Lokalizacja:** linia 5151

**Problem:** Endpoint usuwa plik po ścieżce. Sprawdza tylko rozszerzenie (`.mp3`, `.flac` itd.), nie sprawdza, czy plik jest powiązany z bazą. Użytkownik (lub złośliwa strona) może usunąć dowolny plik audio w systemie.

**Rekomendacja:** Zezwalać na usuwanie wyłącznie plików, które:
- są na liście „sierot” (brak w bazie) wygenerowanej przez aplikację, **albo**
- znajdują się w katalogach, z których załadowano bazę.

---

## Średnie – utrudniają rozwój lub wprowadzają ryzyko

### 4. Brak ograniczeń dla dużych plików (DoS)

**Problem:** `request.files` – brak `MAX_CONTENT_LENGTH`. Użytkownik może wysłać gigabajtowy plik i obciążyć serwer/pamięć.

**Rekomendacja:**
```python
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB
```

---

### 5. Potencjalne race condition przy zapisie plików

**Problem:** Stan globalny (`_songs`, `_vdjfolders` itd.) jest wspólny dla wszystkich requestów. Przy równoległych zapytaniach możliwa niekonsystencja.

**Rekomendacja:** W docelowej wersji rozważyć blokady (np. `threading.Lock`) wokół operacji zapisu lub przetwarzania bazy. Na razie – niskie ryzyko przy jednym użytkowniku lokalnym.

---

### 6. `api/check-updates` – potencjalny XSS w przyszłości

**Lokalizacja:** `static/index.html` ~1101–1104

**Problem:** `d.manualUrl` jest wstawiane do `innerHTML` bez escape. Obecnie endpoint zwraca stały placeholder, więc ryzyko jest zerowe. W przyszłości, jeśli `manualUrl` będzie z zewnętrznego API, może pojawić się XSS.

**Rekomendacja:** Używać `escapeHtml(d.manualUrl)` lub tworzyć link przez `createElement('a')` zamiast `innerHTML`.

---

## Niskie / informacyjne

### 7. Subprocess – bezpieczne użycie

`subprocess.run` jest wywoływany z:
- `osascript` (Mac) – stały skrypt,
- `powershell` (Windows) – stała komenda,
- `open` / `explorer` / `xdg-open` – z `folder` od użytkownika.

`folder` pochodzi z `api/open-folder` – użytkownik może otworzyć dowolny katalog. To raczej feature niż bug, ale łączy się z ogólnym brakiem walidacji ścieżek.

---

### 8. `_eval_filter_condition` – brak `eval()`

**Lokalizacja:** linia 715

Funkcja używa regex i słowników, **nie** `eval()` ani `exec()` – brak typowej podatności na code injection. ✅

---

### 9. ZIP – brak Zip Slip

W `_load_from_zip` pliki są odczytywane do pamięci (`z.read(name)`), nie wypakowywane na dysk – brak typowego Zip Slip. ✅

---

### 10. Licencjonowanie – poprawne

`license_njr.py` i `njr_license.py` – weryfikacja RSA, sprawdzanie machine_id, brak oczywistych luk w logice licencjonowania.

---

## Podsumowanie

| Priorytet | Opis | Działanie |
|-----------|------|-----------|
| 🔴 Krytyczny | CORS zezwala na żądania z dowolnej strony | Ograniczyć origins do localhost |
| 🔴 Krytyczny | Brak walidacji ścieżek – path traversal, usuwanie plików | Dodać `_is_path_safe()` i walidację |
| 🟠 Średni | Brak limitu rozmiaru requestu (DoS) | Ustawić `MAX_CONTENT_LENGTH` |
| 🟡 Niski | XSS w check-updates (przyszłościowe) | Escapować `manualUrl` |

---

## Proponowana kolejność napraw

1. **CORS** – zmiana na `origins=['http://127.0.0.1:*', 'http://localhost:*']` (Flask-CORS obsługuje wildcard w hostcie).
2. **Path validation** – funkcja walidująca ścieżki względem dozwolonych katalogów.
3. **delete-files / orphan-file** – użycie tej walidacji przed usunięciem.
4. **MAX_CONTENT_LENGTH** – ustawienie rozsądnego limitu.

Po tych zmianach konwerter będzie znacznie bezpieczniejszy i gotowy do dalszej pracy bez ryzyka sparaliżowania przez exploity.
