"""Czy dwa pliki to ten sam dźwięk — krótka próbka, zwykle od 50. sekundy.

Cache VDJ odsłuchujemy tylko tak jak quiz: m4a (ftyp) pod innym rozszerzeniem
albo Ogg Opus za nagłówkiem. Zaszyfrowany VDJCACHE i sam link Tidal nie dają próbki.
"""
from __future__ import annotations

import subprocess
import tempfile
import threading
from array import array
from pathlib import Path

_cache: dict[tuple[str, float], bytes] = {}
_prepared: dict[str, str] = {}
_lock = threading.Lock()


def listen_kind(path: str) -> str:
    """file | m4a | ogg da się odtworzyć. tidal | cache | missing — nie."""
    raw = (path or '').strip()
    low = raw.lower()
    if not low:
        return 'missing'
    if low.startswith(('netsearch:', 'streaming:', 'tidal:')) or 'tidal:tracks:' in low:
        return 'tidal'
    if low.startswith('td') and low[2:].split('.', 1)[0].isdigit() and not low.endswith(('.vdjcache', '.vdjsample')):
        return 'tidal'
    p = Path(raw)
    ext = p.suffix.lower()
    if ext in ('.vdjcache', '.vdjsample'):
        if not p.is_file():
            return 'missing'
        try:
            head = p.read_bytes()[:512]
        except OSError:
            return 'missing'
        if b'ftyp' in head:
            return 'm4a'
        if b'OggS' in head:
            return 'ogg'
        return 'cache'
    if not p.is_file():
        return 'missing'
    return 'file'


def _prepare(path: str, kind: str) -> str | None:
    """Ścieżka, którą ffmpeg umie otworzyć. m4a i ogg z obcym rozszerzeniem dostają właściwe."""
    if kind == 'file':
        return path
    with _lock:
        ready = _prepared.get(path)
    if ready:
        return ready
    p = Path(path)
    try:
        head = p.read_bytes()[:512]
    except OSError:
        return None
    if kind == 'm4a':
        idx = head.find(b'ftyp')
        if idx < 4:
            return None
        start = idx - 4
        suffix = '.m4a'
    else:
        idx = head.find(b'OggS')
        if idx < 0:
            return None
        start = idx
        suffix = '.ogg'
    if start == 0 and p.suffix.lower() == suffix:
        prepared = path
    else:
        fd, name = tempfile.mkstemp(suffix=suffix)
        try:
            with p.open('rb') as src, open(fd, 'wb') as dst:
                src.seek(start)
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
        except OSError:
            return None
        prepared = name
    with _lock:
        _prepared[path] = prepared
    return prepared


def _pcm(path: str, start: float, kind: str) -> bytes:
    key = (path, round(start, 1))
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    src = _prepare(path, kind)
    data = b''
    if src:
        cmd = [
            'ffmpeg', '-v', 'error', '-ss', f'{start:.2f}', '-t', '1.5',
            '-i', src, '-ac', '1', '-ar', '8000', '-f', 's16le', '-',
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=12)
            if proc.returncode == 0:
                data = proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            data = b''
    with _lock:
        _cache[key] = data
    return data


def _corr_at(a: bytes, b: bytes, lag: int) -> float | None:
    if len(a) < 4000 or len(b) < 4000:
        return None
    xa = array('h')
    xb = array('h')
    xa.frombytes(a[: len(a) // 2 * 2])
    xb.frombytes(b[: len(b) // 2 * 2])
    if lag >= 0:
        xa = xa[lag:]
    else:
        xb = xb[-lag:]
    n = min(len(xa), len(xb), 10000)
    if n < 2000:
        return None
    step = 2
    count = n // step
    ma = sum(xa[i] for i in range(0, count * step, step)) / count
    mb = sum(xb[i] for i in range(0, count * step, step)) / count
    num = da = db = 0.0
    for i in range(0, count * step, step):
        va = xa[i] - ma
        vb = xb[i] - mb
        num += va * vb
        da += va * va
        db += vb * vb
    if da < 1 or db < 1:
        return None
    return num / ((da ** 0.5) * (db ** 0.5))


def _best_corr(a: bytes, b: bytes) -> float | None:
    base = _corr_at(a, b, 0)
    if base is None or base >= 0.82 or base <= 0.45:
        return base
    best = base
    for lag in (-1600, -800, -400, 400, 800, 1600):
        score = _corr_at(a, b, lag)
        if score is not None and score > best:
            best = score
    return best


def sample_start(duration: float | None, prefer: float | None = None) -> float:
    start = float(prefer) if prefer and prefer > 0 else 50.0
    if duration and duration > 0 and start + 2 > duration:
        start = max(5.0, float(duration) * 0.4)
    return start


def compare_pair(path_a: str, path_b: str, sec: float | None = None, duration: float | None = None) -> dict:
    kinds = (listen_kind(path_a), listen_kind(path_b))
    blocked = next((k for k in kinds if k in ('tidal', 'cache', 'missing')), None)
    if blocked:
        return {'same': None, 'score': None, 'reason': blocked}
    start = sample_start(duration, sec)
    score = _best_corr(_pcm(path_a, start, kinds[0]), _pcm(path_b, start, kinds[1]))
    if score is None:
        return {'same': None, 'score': None, 'reason': 'missing'}
    if score >= 0.82:
        same = True
    elif score <= 0.5:
        same = False
    else:
        same = None
    return {'same': same, 'score': round(score, 3), 'reason': 'ok'}
