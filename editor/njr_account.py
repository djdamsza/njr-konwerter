"""Konto Nowa Jakość Rozrywki dla konwertera.

Hasła nie zapisujemy. Na dysku zostaje tylko token urządzenia i e-mail.
Płatności są na stronie. Ten moduł ich nie liczy i nie zmienia.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ssl_utils import urlopen

SITE = "https://nowajakoscrozrywki.pl"
# Cennik w programie. Sklep na stronie ma osobny, edytowany w panelu wtyczki.
# Następna wersja ma brać pakiety z GET /api/konwerter/packs i pokazać te ceny.
# Do tego czasu przycisk w programie i płatność z programu zostają przy tych kwotach.
PACKS = (
    {"id": "10", "tokens": 10, "grosze": 600, "price": "6 zł"},
    {"id": "50", "tokens": 50, "grosze": 2500, "price": "25 zł"},
    {"id": "100", "tokens": 100, "grosze": 4000, "price": "40 zł"},
)


def site_base() -> str:
    return (os.environ.get("NJR_ACCOUNT_SITE") or SITE).rstrip("/")


class AccountError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def account_dir() -> Path:
    override = (os.environ.get("NJR_ACCOUNT_DIR") or "").strip()
    if override:
        path = Path(override)
    else:
        from platform_paths import app_support_dir
        path = app_support_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_id() -> str:
    path = account_dir() / "install-id"
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        text = str(uuid.uuid4())
        path.write_text(text, encoding="utf-8")
        return text
    except OSError:
        return "local"


def _session_path() -> Path:
    return account_dir() / "account-session.json"


def _read_session() -> dict:
    path = _session_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_session(device_token: str, email: str) -> None:
    _session_path().write_text(
        json.dumps({"deviceToken": device_token, "email": email}, ensure_ascii=False),
        encoding="utf-8",
    )


def logout() -> None:
    path = _session_path()
    if path.is_file():
        path.unlink()


def _remember(payload: dict) -> None:
    from pimp_list import set_token_balance
    if "tokens" not in payload:
        return
    tokens = payload.get("tokens")
    set_token_balance(0 if tokens is None else tokens)


def _public(payload: dict, *, signed_in: bool) -> dict:
    _remember(payload if signed_in else {"tokens": None})
    return {
        "signedIn": signed_in,
        "email": payload.get("email") or "",
        "installId": install_id(),
        "registerUrl": site_base() + "/moje-konto/",
        "buyUrl": site_base() + "/kup/tokeny?install=" + urllib.parse.quote(install_id(), safe=""),
        "tokens": payload.get("tokens"),
        "packs": list(PACKS),
        "subscriptionActive": bool(payload.get("subscriptionActive")),
        "planName": payload.get("planName") or "",
        "subscriptionEndsAt": payload.get("subscriptionEndsAt"),
        "siteReady": True,
    }


def _request(url: str, *, method: str = "GET", body: dict | None = None, token: str = "", timeout: int = 20) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        if url.rstrip("/").endswith("/api/konwerter/ai"):
            raise AccountError(_ai_error_message(exc.code, raw), 401 if exc.code == 401 else 502) from exc
        if "/api/konwerter/google/" in url and exc.code in (401, 404, 410):
            raise AccountError(_google_error_message(exc.code, raw), exc.code) from exc
        if exc.code == 401:
            raise AccountError(
                "Zły e-mail albo hasło, albo ta instalacja jest przypisana do innego konta.",
                401,
            ) from exc
        if exc.code == 409:
            raise AccountError("Brak tokenów na koncie.", 409) from exc
        if exc.code == 404 or raw.lstrip().startswith("<"):
            if url.endswith("/spend") or url.endswith("/checkout"):
                raise AccountError("Strona nie ma jeszcze zakupu tokenów konwertera.", 503) from exc
            raise AccountError(
                "Strona nie ma jeszcze wtyczki konwertera. Potrzebny jest adres /api/konwerter/login.",
                503,
            ) from exc
        raise AccountError("Konto na stronie nie odpowiedziało.", 502) from exc
    except Exception as exc:
        raise AccountError(
            "Nie udało się połączyć z nowajakoscrozrywki.pl. Sprawdź internet.",
            503,
        ) from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise AccountError(
            "Strona nie ma jeszcze wtyczki konwertera. Potrzebny jest adres /api/konwerter/login.",
            503,
        ) from exc
    if not isinstance(parsed, dict):
        raise AccountError("Konto na stronie oddało nieznaną odpowiedź.", 502)
    return parsed


def _google_error_message(code: int, raw: str) -> str:
    parsed = {}
    try:
        loaded = json.loads(raw) if raw else {}
        if isinstance(loaded, dict):
            parsed = loaded
    except json.JSONDecodeError:
        parsed = {}
    message = str(parsed.get("message") or "").strip()
    if message:
        return message
    if code == 404 or (raw or "").lstrip().startswith("<"):
        return "Strona nie ma jeszcze logowania Google. Wgraj wtyczkę konta 1.9.17."
    return "Logowanie Google nie doszło do skutku. W programie kliknij ponownie."


def _google_pending_path() -> Path:
    return account_dir() / "google-login.json"


def _read_google_pending() -> dict:
    path = _google_pending_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    now = time.time()
    return {
        key: value
        for key, value in data.items()
        if isinstance(value, dict) and float(value.get("expires") or 0) > now
    }


def google_start() -> dict:
    """Adres, który program otwiera w przeglądarce. Hasła tu nie ma."""
    state = secrets.token_hex(16)
    pending = _read_google_pending()
    pending[state] = {"expires": time.time() + 600}
    _google_pending_path().write_text(json.dumps(pending), encoding="utf-8")
    url = site_base() + "/api/konwerter/google/start?" + urllib.parse.urlencode({
        "installId": install_id(),
        "state": state,
    })
    return {"url": url, "state": state}


def google_poll(state: str) -> dict:
    """Pyta stronę, czy przeglądarka dokończyła Google. Token zapisuje raz."""
    key = (state or "").strip().lower()
    pending = _read_google_pending()
    if key not in pending:
        raise AccountError("To logowanie Google już wygasło. Kliknij ponownie.")
    payload = _request(
        site_base() + "/api/konwerter/google/result?" + urllib.parse.urlencode({"state": key})
    )
    if payload.get("pending"):
        return {"pending": True}
    device = (payload.get("deviceToken") or "").strip()
    if not device:
        raise AccountError("Strona nie oddała tokenu urządzenia.", 502)
    pending.pop(key, None)
    _google_pending_path().write_text(json.dumps(pending), encoding="utf-8")
    _write_session(device, payload.get("email") or "")
    return _public(payload, signed_in=True)


def login(email: str, password: str) -> dict:
    mail = (email or "").strip()
    secret = password or ""
    if not mail or not secret:
        raise AccountError("Wpisz e-mail i hasło.")
    payload = _request(
        site_base() + "/api/konwerter/login",
        method="POST",
        body={"email": mail, "password": secret, "installId": install_id()},
    )
    device = (payload.get("deviceToken") or "").strip()
    if not device:
        raise AccountError("Strona nie oddała tokenu urządzenia.", 502)
    _write_session(device, payload.get("email") or mail)
    return _public(payload, signed_in=True)


def status() -> dict:
    session = _read_session()
    token = (session.get("deviceToken") or "").strip()
    if not token:
        return _public({}, signed_in=False)
    try:
        payload = _request(site_base() + "/api/konwerter/status", token=token)
    except AccountError as exc:
        if exc.status == 401:
            logout()
            return _public({}, signed_in=False)
        out = _public({"email": session.get("email") or ""}, signed_in=True)
        out["siteReady"] = False
        out["error"] = exc.message
        return out
    if payload.get("email"):
        _write_session(token, payload.get("email") or session.get("email") or "")
    else:
        payload["email"] = session.get("email") or ""
    return _public(payload, signed_in=True)


def _device_token() -> str:
    return (_read_session().get("deviceToken") or "").strip()


def has_session() -> bool:
    """Czy na tym komputerze jest zapisane konto NJR. Nie pyta strony."""
    return bool(_device_token())


def _ai_error_message(code: int, raw: str) -> str:
    if code == 401:
        return "Zaloguj się, żeby użyć AI."
    parsed = {}
    try:
        loaded = json.loads(raw) if raw else {}
        if isinstance(loaded, dict):
            parsed = loaded
    except json.JSONDecodeError:
        parsed = {}
    if code == 404 or (raw or "").lstrip().startswith("<"):
        return "Strona nie ma jeszcze połączenia z AI."
    if parsed.get("error") == "no_key":
        return (
            "AI na stronie nie jest włączone. W WordPressie otwórz Fotobudka — konto klienta, "
            "wklej klucz w pole Klucz AI Playlist Pro i zapisz. Puste pole zostawia poprzedni klucz."
        )
    if code == 503:
        return "AI na stronie nie jest jeszcze włączone."
    message = str(parsed.get("message") or "").strip()
    return message or "Model nie odpowiedział."


def ask_model(prompt: str, timeout: int = 90) -> dict:
    """Pyta model przez stronę. Tokenu nie zdejmuje."""
    token = _device_token()
    if not token:
        raise AccountError("Zaloguj się, żeby użyć AI.", 401)
    text = (prompt or "").strip()
    if not text:
        raise AccountError("Pusty tekst do modelu.")
    payload = _request(
        site_base() + "/api/konwerter/ai",
        method="POST",
        body={"prompt": text},
        token=token,
        timeout=max(30, int(timeout) + 20),
    )
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        message = str(payload.get("message") or "").strip()
        raise AccountError(message or "Strona nie oddała odpowiedzi modelu.", 502)
    return {"model": str(payload.get("model") or ""), "sent": text, "answer": answer}


def spend_tokens(count: int) -> dict:
    """Odejmuje tokeny na koncie. Zwraca stan po odjęciu."""
    token = _device_token()
    if not token:
        raise AccountError("Zaloguj się, żeby użyć AI.", 401)
    n = int(count or 0)
    if n < 1:
        raise AccountError("Zła liczba tokenów.")
    payload = _request(
        site_base() + "/api/konwerter/spend",
        method="POST",
        body={"count": n},
        token=token,
    )
    if payload.get("error") == "no_tokens":
        raise AccountError("Brak tokenów na koncie.", 409)
    if "tokens" not in payload:
        raise AccountError("Strona nie oddała stanu tokenów.", 502)
    return _public(payload, signed_in=True)


def checkout_pack(pack_id: str) -> str:
    """Prosi stronę o adres Stripe dla jednej z trzech paczek."""
    token = _device_token()
    if not token:
        raise AccountError("Zaloguj się, żeby kupić tokeny.", 401)
    chosen = next((item for item in PACKS if item["id"] == str(pack_id or "").strip()), None)
    if chosen is None:
        raise AccountError("Nie ma takiej paczki.")
    payload = _request(
        site_base() + "/api/konwerter/checkout",
        method="POST",
        body={"pack": chosen["id"]},
        token=token,
    )
    url = str(payload.get("url") or "").strip()
    if not (url.startswith("https://checkout.stripe.com/") or url.startswith("https://nowajakoscrozrywki.pl/")):
        raise AccountError("Strona nie oddała adresu płatności.", 502)
    return url
