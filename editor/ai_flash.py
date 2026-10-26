"""Wywołanie modelu przez zalogowane konto na stronie.

Klucz zostaje na nowajakoscrozrywki.pl. Program wysyła sam tekst
i dostaje odpowiedź. Tokenów to nie odejmuje — robi to osobne wywołanie.
"""
from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

def _dotenv_paths():
    """Klucz zostaje w editor/.env na dysku. Spakowany program nie ma tego pliku w środku."""
    paths = [Path(__file__).resolve().parent / ".env"]
    home = Path.home()
    paths.append(home / "Documents" / "njr-konwerter" / "editor" / ".env")
    paths.append(home / "Library" / "Application Support" / "NJR Konwerter" / ".env")
    return paths
_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
)
_blocked_until: dict[str, float] = {}


def _key_from_env_file(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, value = text.split("=", 1)
        if name.strip() == "GEMINI_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


def gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    seen = set()
    for path in _dotenv_paths():
        marker = str(path)
        if marker in seen:
            continue
        seen.add(marker)
        found = _key_from_env_file(path)
        if found:
            return found
    return ""


def gemini_model() -> str:
    return (os.environ.get("GEMINI_MODEL") or _MODELS[0]).strip() or _MODELS[0]


def _local_preview(text: str, timeout: int, models: tuple[str, ...] | None) -> dict | None:
    """Zapas, dopóki strona nie ma adresu AI. Klucz zostaje w editor/.env, nie w programie."""
    key = gemini_api_key()
    if not key:
        return None
    last_error = "Model nie odpowiedział."
    saw_limit = False
    for model in _candidates(models):
        try:
            data = _post_interaction(key, model, text, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = f"Model odrzucił zapytanie ({exc.code})."
            if _should_try_next(exc.code, detail):
                saw_limit = True
                _mark_blocked(model, detail)
                continue
            raise ValueError(last_error) from exc
        except (TimeoutError, socket.timeout):
            _mark_blocked(model, "timeout")
            last_error = "Model nie odpowiedział w czasie."
            continue
        except urllib.error.URLError as exc:
            raise ValueError(f"Brak połączenia z modelem. {exc.reason}") from exc
        answer = _answer_text(data)
        if answer:
            return {"model": model, "sent": text, "answer": answer}
        last_error = "Model nie oddał tekstu."
    if saw_limit:
        raise ValueError("Limit zapytań modelu jest teraz wyczerpany. Spróbuj później.")
    raise ValueError(last_error)


def flash_preview(prompt: str, max_chars: int = 4000, timeout: int = 45, models: tuple[str, ...] | None = None) -> dict:
    """Wysyła tekst na stronę i zwraca odpowiedź. Klucza nie ma w programie."""
    text = (prompt or "").strip()
    if not text:
        raise ValueError("Pusty tekst do modelu.")
    if len(text) > max_chars:
        text = text[:max_chars]
    from njr_account import AccountError, ask_model

    try:
        return ask_model(text, timeout=timeout)
    except AccountError as exc:
        raise ValueError(exc.message) from exc


def _model_order(preferred: tuple[str, ...] | None = None) -> list[str]:
    order = []
    for name in (*(preferred or ()), gemini_model(), *_MODELS):
        if name and name not in order:
            order.append(name)
    return order


def _candidates(preferred: tuple[str, ...] | None = None) -> list[str]:
    order = _model_order(preferred)
    now = time.time()
    open_models = [name for name in order if _blocked_until.get(name, 0) <= now]
    return open_models or order


def _should_try_next(code: int, detail: str) -> bool:
    if code in (404, 408, 429, 500, 502, 503, 504):
        return True
    low = (detail or "").lower()
    return any(word in low for word in ("quota", "rate limit", "rate-limit", "resource_exhausted", "resource exhausted", "too many requests"))


def _cooldown_seconds(detail: str) -> int:
    text = (detail or "").lower()
    if any(word in text for word in ("per day", "daily", "requests per day")):
        return 12 * 3600
    match = re.search(r"retry in (\d+)", text)
    if match:
        return min(int(match.group(1)) + 2, 3600)
    match = re.search(r"retrydelay[^0-9]{0,8}(\d+)", text)
    if match:
        return min(int(match.group(1)) + 2, 3600)
    if "timeout" in text:
        return 60
    return 30 * 60


def _mark_blocked(model: str, detail: str) -> None:
    _blocked_until[model] = time.time() + _cooldown_seconds(detail)


def _post_interaction(key: str, model: str, text: str, timeout: int = 45) -> dict:
    payload = json.dumps({
        "model": model,
        "input": text,
        "store": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _answer_text(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts = []
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        content = step.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str) and block.strip():
                    parts.append(block.strip())
                elif isinstance(block, dict) and (block.get("text") or "").strip():
                    parts.append(str(block["text"]).strip())
    return "\n".join(parts).strip()
