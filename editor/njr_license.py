"""
Licencjonowanie NJR konwerter – tylko eksport wymaga licencji.

Bezpłatna wersja: pełna edycja bez limitu czasu.
Eksport (VDJ, Serato, Rekordbox, DJXML, Kopia zapasowa, ID3): wymaga klucza.

Format klucza: IMPREZJA-RSA (ten sam co Imprezja Quiz).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Optional

LICENSE_FILE = Path.home() / '.njr-license'

# Klucz publiczny RSA – ten sam co w license.js (Imprezja)
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAznhSchHyVk4523mOSXs3
iRi38Lvz9SCcPYNi+yfo7xlklaUWDrkxsADfueO4Rd/YJkmYj4Cm3BJg2KTgMlxi
sfWI3Un9nWWCfDrnDVU+u0YqwhCWqTlCfewRuu7TxpjsNglNEJRmh9umBkZWcFiY
XTo23kgfZu78nBtT21zH3NIaIWXnYEPzEeqtxqWhXHGHkuZTnYqdVhcHKfAKPs0A
gckiSM37sAWinB74DG6UrPEcxMxUdGmPRNp4qzMReMvNPgVhPw6Cl+epa2GQgYCL
/uJpyNe1lvyhxMMsnXYxDtiBlOwf0iEZraf5oWw9ybjrTq51UAmfplSbUlXc74un
7wIDAQAB
-----END PUBLIC KEY-----"""


def get_machine_id() -> str:
    """Identyfikator komputera – hostname + platform (stabilny przy zmianie sieci)."""
    hostname = platform.node()
    plat = platform.system().lower()
    raw = f"{hostname}-{plat}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _base64url_decode(s: str) -> bytes:
    s = s.replace('-', '+').replace('_', '/')
    pad = 4 - len(s) % 4
    if pad != 4:
        s += '=' * pad
    return base64.b64decode(s)


def verify_license_key(key: str) -> dict:
    """
    Weryfikuje klucz licencyjny.
    Zwraca: {valid: bool, type: str, reason?: str, expires?: int}
    """
    if not key or not isinstance(key, str):
        return {'valid': False, 'reason': 'Nieprawidłowy format klucza'}

    key = key.strip()

    # Klucz testowy
    if key == 'IMPREZJA-TEST-TEST-TEST-TEST':
        return {'valid': True, 'type': 'test', 'expires': None}

    # Format RSA
    m = re.match(r'^IMPREZJA-RSA-([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$', key)
    if m:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend

            payload_b64, sig_b64 = m.group(1), m.group(2)
            payload_bytes = _base64url_decode(payload_b64)
            payload_str = payload_bytes.decode('utf-8')
            payload = json.loads(payload_str)
            signature = _base64url_decode(sig_b64)

            pub_key = serialization.load_pem_public_key(
                PUBLIC_KEY_PEM.encode(), backend=default_backend()
            )
            pub_key.verify(
                signature,
                payload_str.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )

            machine_id = get_machine_id()
            if payload.get('m') != machine_id:
                return {'valid': False, 'reason': 'Klucz nie pasuje do tego komputera'}

            lic_type = payload.get('t', 'LT')
            if lic_type not in ('LT', '1M', '3M', '6M', '1Y'):
                return {'valid': False, 'reason': 'Nieznany typ licencji'}

            expires = payload.get('e')
            return {'valid': True, 'type': lic_type, 'expires': expires}
        except Exception as e:
            return {'valid': False, 'reason': f'Nieprawidłowy format klucza: {e}'}

    # Stary format (dożywotnia)
    key_upper = key.upper()
    if re.match(r'^IMPREZJA-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})$', key_upper):
        key_parts = re.sub(r'IMPREZJA-?', '', key_upper).replace('-', '')
        machine_id = get_machine_id()
        expected = hashlib.sha256(f'IMPREZJA-{machine_id}'.encode()).hexdigest()[:16].upper()
        if key_parts[:16] == expected:
            return {'valid': True, 'type': 'LT', 'expires': None}
        return {'valid': False, 'reason': 'Klucz nie pasuje do tego komputera'}

    return {'valid': False, 'reason': 'Nieprawidłowy format klucza'}


def check_license() -> dict:
    """
    Sprawdza zapisaną licencję.
    Zwraca: {can_export: bool, valid: bool, type?: str, reason?: str, machine_id: str}
    """
    machine_id = get_machine_id()
    result = {'can_export': False, 'valid': False, 'machine_id': machine_id}

    if not LICENSE_FILE.exists():
        return result

    try:
        data = json.loads(LICENSE_FILE.read_text(encoding='utf-8'))
        key = data.get('key', '').strip()
        if not key:
            return result

        verification = verify_license_key(key)
        if not verification.get('valid'):
            return result

        import time
        expires = data.get('expires') or verification.get('expires')
        if expires and expires < int(time.time() * 1000):
            result['reason'] = 'Licencja wygasła'
            return result

        result['valid'] = True
        result['can_export'] = True
        result['type'] = verification.get('type', data.get('type', 'LT'))
        return result
    except Exception:
        return result


def save_license_key(key: str) -> bool:
    """Zapisuje i weryfikuje klucz. Zwraca True jeśli OK."""
    verification = verify_license_key(key)
    if not verification.get('valid'):
        return False

    import time
    expires = None
    lic_type = verification.get('type', 'LT')
    if lic_type in ('1M', '3M', '6M', '1Y'):
        durations = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365}
        days = durations.get(lic_type, 30)
        expires = int(time.time() * 1000) + days * 24 * 60 * 60 * 1000

    license_data = {
        'key': key.strip(),
        'machineId': get_machine_id(),
        'activated': int(time.time() * 1000),
        'expires': expires,
        'type': lic_type,
    }
    try:
        LICENSE_FILE.write_text(json.dumps(license_data, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def can_export() -> bool:
    """Czy użytkownik może eksportować (ma ważną licencję)."""
    return check_license().get('can_export', False)
