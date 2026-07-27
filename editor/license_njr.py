"""
Licencjonowanie NJR Konwerter — tryb open source.

Eksport i pełna funkcjonalność są dostępne bez klucza.
Moduł zostaje dla kompatybilności API (`/api/license/*`); w przyszłości
można tu przywrócić opcjonalne licencje komercyjne.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

LICENSE_FILE = Path.home() / '.njr-license'


def get_machine_id() -> str:
    """Identyfikator komputera (informacyjny; nie blokuje eksportu)."""
    import platform
    hostname = platform.node()
    plat = platform.system().lower()
    h = hashlib.sha256(f'{hostname}-{plat}'.encode()).hexdigest()
    return h[:16]


def verify_license_key(license_key: str) -> dict:
    """W trybie open source każdy niepusty klucz uznajemy za OK (opcjonalnie)."""
    if not license_key or not isinstance(license_key, str) or not license_key.strip():
        return {'valid': False, 'reason': 'Brak klucza (opcjonalny w wersji open source)'}
    return {'valid': True, 'type': 'OSS', 'expires': None}


def save_license_key(license_key: str) -> bool:
    """Zapis opcjonalnego klucza (nie jest wymagany do eksportu)."""
    try:
        verification = verify_license_key(license_key)
        if not verification.get('valid'):
            return False
        data = {
            'key': license_key.strip(),
            'machineId': get_machine_id(),
            'activated': int(__import__('time').time() * 1000),
            'expires': None,
            'type': verification.get('type') or 'OSS',
        }
        LICENSE_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def check_export_license() -> dict:
    """Open source: eksport zawsze dozwolony."""
    return {
        'allowed': True,
        'machineId': get_machine_id(),
        'reason': None,
        'mode': 'opensource',
    }
