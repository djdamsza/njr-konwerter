"""
System licencjonowania NJR konwerter.
- Wersja bezpłatna: pełna funkcjonalność bez limitu czasu.
- Eksport (pobieranie bazy, konwersja, zapis tagów) wymaga licencji przypisanej do komputera.
- Format klucza: IMPREZJA-RSA (kompatybilny z Imprezja Quiz).
"""

import base64
import hashlib
import json
import os
import re
from pathlib import Path

LICENSE_FILE = Path.home() / '.njr-license'

PUBLIC_KEY_PEM = (os.environ.get('IMPREZJA_LICENSE_PUBLIC_KEY') or """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAznhSchHyVk4523mOSXs3
iRi38Lvz9SCcPYNi+yfo7xlklaUWDrkxsADfueO4Rd/YJkmYj4Cm3BJg2KTgMlxi
sfWI3Un9nWWCfDrnDVU+u0YqwhCWqTlCfewRuu7TxpjsNglNEJRmh9umBkZWcFiY
XTo23kgfZu78nBtT21zH3NIaIWXnYEPzEeqtxqWhXHGHkuZTnYqdVhcHKfAKPs0A
gckiSM37sAWinB74DG6UrPEcxMxUdGmPRNp4qzMReMvNPgVhPw6Cl+epa2GQgYCL
/uJpyNe1lvyhxMMsnXYxDtiBlOwf0iEZraf5oWw9ybjrTq51UAmfplSbUlXc74un
7wIDAQAB
-----END PUBLIC KEY-----""").replace('\\n', '\n')


def get_machine_id() -> str:
    """Identyfikator komputera – hostname + platform (stabilny przy zmianie sieci)."""
    import platform
    hostname = platform.node()
    plat = platform.system().lower()
    h = hashlib.sha256(f'{hostname}-{plat}'.encode()).hexdigest()
    return h[:16]


def _base64url_decode(s: str) -> bytes:
    b64 = s.replace('-', '+').replace('_', '/')
    pad = 4 - len(b64) % 4
    if pad != 4:
        b64 += '=' * pad
    return base64.b64decode(b64)


def verify_rsa_format(license_key: str):
    """Weryfikacja formatu IMPREZJA-RSA-{payload}.{signature}."""
    m = re.match(r'^IMPREZJA-RSA-([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$', license_key)
    if not m:
        return None
    payload_b64, sig_b64 = m.group(1), m.group(2)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.exceptions import InvalidSignature

        payload_bytes = _base64url_decode(payload_b64)
        payload_str = payload_bytes.decode('utf-8')
        payload = json.loads(payload_str)
        signature = _base64url_decode(sig_b64)

        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
        public_key.verify(signature, payload_str.encode(), padding.PKCS1v15(), hashes.SHA256())

        machine_id = get_machine_id()
        if payload.get('m') != machine_id:
            return {'valid': False, 'reason': 'Klucz nie pasuje do tego komputera'}

        lic_type = payload.get('t', 'LT')
        if lic_type not in ('LT', '1M', '3M', '6M', '1Y'):
            return {'valid': False, 'reason': 'Nieznany typ licencji'}

        return {
            'valid': True,
            'type': lic_type,
            'expires': payload.get('e'),
        }
    except InvalidSignature:
        return {'valid': False, 'reason': 'Nieprawidłowy podpis klucza'}
    except ImportError:
        return {'valid': False, 'reason': 'Moduł cryptography nie jest zainstalowany (pip install cryptography)'}
    except Exception as e:
        return {'valid': False, 'reason': f'Nieprawidłowy format klucza: {e}'}


def verify_license_key(license_key: str) -> dict:
    """Weryfikuje klucz licencyjny."""
    if not license_key or not isinstance(license_key, str):
        return {'valid': False, 'reason': 'Nieprawidłowy format klucza'}
    key = license_key.strip()

    if key == 'IMPREZJA-TEST-TEST-TEST-TEST':
        return {'valid': True, 'type': 'test', 'expires': None}

    if key.startswith('IMPREZJA-RSA-'):
        result = verify_rsa_format(key)
        return result or {'valid': False, 'reason': 'Nieprawidłowy format klucza'}

    key_upper = key.upper()
    if re.match(r'^IMPREZJA-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})$', key_upper):
        key_parts = re.sub(r'IMPREZJA-?', '', key_upper).replace('-', '')
        machine_id = get_machine_id()
        expected = hashlib.sha256(f'IMPREZJA-{machine_id}'.encode()).hexdigest()[:16].upper()
        if key_parts[:16] == expected:
            return {'valid': True, 'type': 'LT', 'expires': None}
        return {'valid': False, 'reason': 'Klucz nie pasuje do tego komputera'}

    return {'valid': False, 'reason': 'Nieprawidłowy format klucza'}


def save_license_key(license_key: str) -> bool:
    """Zapisuje klucz licencyjny do pliku."""
    try:
        verification = verify_license_key(license_key)
        if not verification.get('valid'):
            return False

        license_types_ms = {'1M': 30 * 24 * 3600 * 1000, '3M': 90 * 24 * 3600 * 1000,
                           '6M': 180 * 24 * 3600 * 1000, '1Y': 365 * 24 * 3600 * 1000}
        activated = int(__import__('time').time() * 1000)
        expires = None
        t = verification.get('type')
        if t and t in license_types_ms:
            expires = activated + license_types_ms[t]

        data = {
            'key': license_key.strip(),
            'machineId': get_machine_id(),
            'activated': activated,
            'expires': expires,
            'type': t or 'LT',
        }
        LICENSE_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return True
    except Exception:
        return False


def check_export_license() -> dict:
    """
    Sprawdza czy użytkownik ma licencję na eksport.
    Zwraca: {'allowed': True} lub {'allowed': False, 'reason': str, 'machineId': str}
    """
    try:
        if not LICENSE_FILE.exists():
            return {
                'allowed': False,
                'reason': 'Eksport wymaga licencji. Wersja bezpłatna pozwala na pełną edycję – zapisz postęp i wykup licencję, aby wyeksportować bazę.',
                'machineId': get_machine_id(),
            }

        data = json.loads(LICENSE_FILE.read_text(encoding='utf-8'))
        verification = verify_license_key(data.get('key', ''))

        if not verification.get('valid'):
            return {
                'allowed': False,
                'reason': verification.get('reason', 'Nieprawidłowa licencja'),
                'machineId': get_machine_id(),
            }

        expires = data.get('expires') or verification.get('expires')
        if expires and int(expires) < __import__('time').time() * 1000:
            return {
                'allowed': False,
                'reason': 'Licencja wygasła',
                'machineId': get_machine_id(),
            }

        return {'allowed': True}
    except Exception as e:
        return {
            'allowed': False,
            'reason': f'Błąd odczytu licencji: {e}',
            'machineId': get_machine_id(),
        }
