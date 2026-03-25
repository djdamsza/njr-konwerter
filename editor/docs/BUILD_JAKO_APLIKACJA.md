# NJR konwerter / edytor – przebudowa na aplikację desktop (macOS + Windows)

Jak przebudować skrypt Pythona w aplikację działającą na macOS i Windows z licencjonowaniem jak Imprezja Quiz.

---

## 1. Architektura Imprezja Quiz (wzór)

- **Electron** – opakowuje aplikację w okno desktop
- **Node.js (Express)** – serwer HTTP na porcie 3000
- **license.js** – trial 14 dni, weryfikacja RSA, klucze czasowe/dożywotnie
- **electron-builder** – pakowanie do DMG (macOS) i NSIS (Windows)
- **Stripe** – płatności, dostarczanie kluczy po zakupie

---

## 2. Różnice NJR konwerter vs Imprezja

| Aspekt | Imprezja Quiz | NJR konwerter |
|--------|---------------|---------------|
| Backend | Node.js (server.js) | **Python Flask** (app.py) |
| Port | 3000 | 5050 |
| Uruchomienie | `node server.js` | `python app.py` |

---

## 3. Strategie przebudowy

### Opcja A: Electron + Python (zalecana)

Electron uruchamia proces Pythona zamiast Node.js.

**Kroki:**

1. **Utworzyć `njr-electron-main.js`** (wzór: electron-main.js):
   - Zamiast `spawn('node', ['server.js'])` → `spawn('python3', ['app.py'])` lub ścieżka do spakowanego Pythona
   - Okno ładuje `http://127.0.0.1:5050`
   - Single-instance lock, auto-updater (opcjonalnie)

2. **PyInstaller** – spakować Pythona + zależności do jednego pliku:
   ```bash
   cd tools/vdj-database-editor
   pip install pyinstaller
   pyinstaller --onefile --name njr-converter app.py
   ```
   Wynik: `dist/njr-converter` (macOS) lub `njr-converter.exe` (Windows)

3. **Electron** – w `getAppRoot()` dodać obsługę `njr-converter`:
   - W pakiecie: `resources/njr-converter` (lub .exe)
   - `spawn(path.join(resources, 'njr-converter'), [], { cwd: resources })`

4. **Licencja** – dodać `license.js` do projektu Electron:
   - Sprawdzenie licencji przed otwarciem okna
   - Jeśli brak licencji → okno z `license-required.html` (jak w Imprezji)
   - API `/api/license/status`, `/api/license/activate` – trzeba dodać do Flask (lub osobny mini-serwer Node tylko do licencji)

5. **electron-builder** – konfiguracja:
   - `productName: "NJR konwerter"`
   - `appId: "pl.imprezja.njr-converter"`
   - `files` – dodać `tools/vdj-database-editor/**`, `njr-converter` (binarka PyInstaller)

**Problem:** API licencji jest w Node (license.js). Flask nie ma dostępu. Rozwiązania:
- **A1:** Mini-serwer Node (np. `license-server.js`) na porcie 5051 – Flask proxy do niego
- **A2:** Portować logikę licencji do Pythona (cryptography, RSA) – więcej pracy
- **A3:** Electron sprawdza licencję przed startem, Flask nie wie o licencji – najprostsze

### Opcja B: Electron + Node wrapper

Node.js uruchamia Pythona jako child process i serwuje frontend.

- `server-njr.js` – Express na 5050, proxy do Pythona lub uruchamia `python app.py` i proxy do localhost:5050
- Skomplikowane – dwa serwery (Node + Python)

### Opcja C: Tylko PyInstaller (bez Electron)

- PyInstaller pakuje Flask + frontend
- PyInstaller uruchamia serwer i otwiera przeglądarkę (`webbrowser.open`)
- Brak okna natywnego – użytkownik widzi przeglądarkę
- Licencja: portować `license.js` do Pythona (RSA, trial)

---

## 4. Konkretny plan (Opcja A – zalecana)

### Krok 1: PyInstaller dla NJR

```bash
cd /Users/test/Documents/VoteBattle/tools/vdj-database-editor
pip install -r requirements.txt  # jeśli jest
pyinstaller --onefile --add-data "static:static" --name njr-converter app.py
```

Dostosować `app.py` – ścieżka do `static` przy pakowaniu (PyInstaller używa `sys._MEIPASS`).

### Krok 2: Nowy projekt Electron dla NJR

Struktura:

```
njr-converter-app/
├── package.json
├── electron-main.js      # wzór z VoteBattle, spawn Python
├── license.js            # skopiować z VoteBattle
├── public/
│   └── license-required.html
├── tools/
│   └── vdj-database-editor/
│       ├── app.py
│       ├── static/
│       └── ...
└── dist/
    └── njr-converter     # binarka z PyInstaller (lub .exe)
```

### Krok 3: Licencja w Electron

- Przed `createWindow()`: `license.checkLicense()`
- Jeśli `!valid` → okno z `license-required.html` (aktywacja, Machine ID)
- Po aktywacji – restart lub odblokowanie
- API aktywacji: endpoint w Flask lub osobny mini-serwer Node

### Krok 4: electron-builder

```json
{
  "name": "njr-converter",
  "productName": "NJR konwerter",
  "main": "electron-main.js",
  "build": {
    "appId": "pl.imprezja.njr-converter",
    "mac": { "target": "dmg", "category": "public.app-category.utilities" },
    "win": { "target": "nsis", "executableName": "NJRKonwerter" }
  }
}
```

### Krok 5: Stripe + dostarczanie kluczy

- Jak w Imprezji: stripe-shop, webhook, `/api/license/deliver`
- Lookup keys: `njr-1m`, `njr-3m`, `njr-12m`, `njr-lifetime`
- Generator kluczy: ten sam `scripts/generate-license-key.js` z parametrem produktu (lub osobny skrypt dla NJR)

---

## 5. Zabezpieczenia (jak Imprezja Quiz)

| Element | Opis |
|---------|------|
| **Trial 14 dni** | Plik `~/.njr-trial-start` (lub `.imprezja-trial-start` z prefiksem) |
| **Machine ID** | hostname + platform (stabilny przy zmianie sieci) |
| **RSA** | Klucz publiczny w aplikacji, prywatny tylko w generatorze |
| **Klucze** | Format `IMPREZJA-RSA-{payload}.{signature}` – można użyć tego samego dla NJR |
| **asar** | `asar: true` w electron-builder – kod w archiwum |

---

## 6. Pliki do przygotowania

1. **electron-main-njr.js** – fork electron-main.js z spawn Pythona
2. **license.js** – skopiować, ewentualnie zmienić `LICENSE_FILE` na `~/.njr-license`
3. **public/license-required.html** – strona aktywacji (dostosować tekst)
4. **package.json** – build dla NJR
5. **Skrypt build** – PyInstaller + electron-builder w jednym flow

---

## 7. Szybki start (minimalny)

```bash
# 1. PyInstaller
cd tools/vdj-database-editor
pyinstaller --onefile --name njr-converter app.py

# 2. Electron (w głównym VoteBattle – rozszerzyć)
# Dodać target "njr" w package.json
npm run build:njr   # build:mac + build:win z inną konfiguracją
```

---

## 8. Tidal embed – auto-play bez Tampermonkey

W trybie przeglądarki (Flask) embed Tidal w iframe nie odtwarza automatycznie – użytkownik musi zainstalować Tampermonkey + userscript. **Tampermonkey nie da się zintegrować z aplikacją** (to rozszerzenie przeglądarki).

W **Electron** można to obejść bez Tampermonkey:

1. Zamienić `<iframe>` na `<webview>` dla embedów Tidal.
2. Użyć atrybutu `preload` wskazującego na `scripts/tidal-embed-preload.js`.
3. Preload uruchamia się w kontekście embed.tidal.com i automatycznie klika Play.

```html
<!-- Zamiast iframe -->
<webview id="tidalPlayerBarIframe" src="https://embed.tidal.com/tracks/123"
  preload="file:///ścieżka/do/scripts/tidal-embed-preload.js"
  style="width:100%; height:120px;"></webview>
```

Ścieżka do preload musi być absolutna (np. `path.join(__dirname, 'tools/vdj-database-editor/scripts/tidal-embed-preload.js')`). W `index.html` można wykryć Electron (`window.electronAPI` lub `navigator.userAgent`) i renderować webview zamiast iframe.

---

## 9. Uwagi

- **Python w Electron:** Na Windows użytkownik może nie mieć Pythona – dlatego PyInstaller jest konieczny.
- **Wspólna licencja:** Można użyć tego samego systemu licencji (IMPREZJA-RSA) dla obu produktów – jeden klucz może uprawniać do obu lub osobne produkty w Stripe.
- **Code signing:** Na macOS `forceCodeSigning: true` + certyfikat Apple; na Windows – certyfikat EV dla instalatora (opcjonalnie).
