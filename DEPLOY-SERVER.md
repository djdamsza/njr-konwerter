# Wgranie NJR Konwertera na serwer

Plik binarny po buildzie leży w `releases/` — kopiujesz go na VPS / hosting (**SSH**) i serwujesz przez **HTTPS** (np. nginx).

## 1. Przygotuj plik lokalnie

1. Zbuduj aplikację ([`BUILD.md`](BUILD.md)).
2. Nazwy z wersją generuje `scripts/build-local.sh`; ewentualnie dopisz sufiks platformy ręcznie.
3. Sumy kontrolne:

   ```bash
   cd releases
   shasum -a 256 NJR-konwerter* > SHA256SUMS.txt
   ```

   Na Linuxie: `sha256sum NJR-konwerter* > SHA256SUMS.txt`.

## 2. Katalog na serwerze

Przykład:

```text
/var/www/twoja-domena/downloads/njr/
  NJR-konwerter-1.0.0
  NJR-konwerter-1.0.0.exe
  SHA256SUMS.txt
```

## 3. scp / rsync

Szablon: [`scripts/deploy-to-server.example.sh`](scripts/deploy-to-server.example.sh).

```bash
scp releases/NJR-konwerter-1.0.0.exe user@serwer:/var/www/.../downloads/njr/
rsync -avz --progress releases/ user@serwer:/var/www/.../downloads/njr/
```

## 4. Nginx — przykład

```nginx
location /downloads/njr/ {
    alias /var/www/twoja-domena/downloads/njr/;
    default_type application/octet-stream;
    add_header X-Content-Type-Options nosniff;
}
```

`sudo nginx -t && sudo systemctl reload nginx`

## 5. GitHub Releases

Zamiast własnego serwera: release na GitHubie z załączonymi binariami z `releases/`.
