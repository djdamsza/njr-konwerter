"""
Zapis / odczyt Serato Markers2 (hot cues) w plikach audio.

Format wg Holzhaus/serato-tags + Mixxx:
  ID3 GEOB „Serato Markers2”: \\x01\\x01 + base64(payload) + padding do ≥470 B
  payload: \\x01\\x01 + wpisy CUE/COLOR/BPMLOCK + \\x00
  M4A/MP4: wymagane OBA atomy ----:com.serato.dj:markers (Markers_)
  oraz markersv2 — bez „markers” Serato ignoruje cue 0–4.

Serato nie trzyma cue w Database V2 — tylko w tagach plików.
"""
from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Optional

from unified_model import CuePoint, LoopPoint, Track

# Domyślne kolory hot cue Serato (RGB) — slot 0–7
_SERATO_DEFAULT_COLORS: list[bytes] = [
    bytes([0xCC, 0x00, 0x00]),
    bytes([0xCC, 0x88, 0x00]),
    bytes([0x00, 0x00, 0xCC]),
    bytes([0xCC, 0xCC, 0x00]),
    bytes([0x00, 0xCC, 0x00]),
    bytes([0xCC, 0x00, 0xCC]),
    bytes([0x00, 0xCC, 0xCC]),
    bytes([0xAA, 0xAA, 0xAA]),
]

_SUPPORTED_EXT = {".mp3", ".flac", ".m4a", ".mp4", ".aiff", ".aif", ".wav"}


def _is_streaming_path(path: str) -> bool:
    p = (path or "").lower()
    return any(
        p.startswith(x)
        for x in (
            "tidal:",
            "soundcloud:",
            "beatport:",
            "file://localhosttidal:",
            "file://localhostsoundcloud:",
            "file://localhostbeatport:",
        )
    )


def serato_cue_index(num: int) -> Optional[int]:
    """VDJ/RB Num 1–8 → slot 0–7; Num 0–7 też (legacy)."""
    if 1 <= num <= 8:
        return num - 1
    if 0 <= num < 8:
        return num
    return None


def normalize_serato_cue_points(cue_points: list[CuePoint]) -> list[CuePoint]:
    """
    Mapuje cue VDJ na max 8 slotów Serato (0–7).
    Num 1–8 / 0–7 idą w swoje sloty (pierwszy wygrywa przy duplikacie).
    Num poza zakresem (np. 9, 10) wypełniają wolne sloty.
    """
    primary: list[Optional[CuePoint]] = [None] * 8
    overflow: list[CuePoint] = []
    for cp in cue_points or []:
        slot = serato_cue_index(int(cp.num))
        if slot is None:
            overflow.append(cp)
            continue
        if primary[slot] is None:
            primary[slot] = cp
        # duplikat slotu — pomijamy (jak wcześniej: first wins)
    for cp in overflow:
        try:
            free = next(i for i, x in enumerate(primary) if x is None)
        except StopIteration:
            break
        primary[free] = CuePoint(
            name=cp.name or f"Cue {free + 1}",
            pos=cp.pos,
            num=free + 1,
            color=cp.color,
        )
    out: list[CuePoint] = []
    for i, cp in enumerate(primary):
        if cp is None:
            continue
        slot = serato_cue_index(int(cp.num))
        if slot != i:
            out.append(
                CuePoint(
                    name=cp.name or f"Cue {i + 1}",
                    pos=cp.pos,
                    num=i + 1,
                    color=cp.color,
                )
            )
        else:
            out.append(cp)
    return out


def _rgb_from_cue(cp: CuePoint, slot: int) -> bytes:
    if cp.color is not None:
        # VDJ ARGB 32-bit lub RGB
        c = int(cp.color) & 0xFFFFFFFF
        if c > 0xFFFFFF:
            r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        else:
            r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        if r or g or b:
            return bytes([r, g, b])
    return _SERATO_DEFAULT_COLORS[slot % len(_SERATO_DEFAULT_COLORS)]


def _cue_entry_bytes(index: int, position_ms: int, color: bytes, name: str) -> bytes:
    """Payload wpisu CUE (bez nazwy typu / length)."""
    label = (name or "").encode("utf-8")[:48]
    return b"".join(
        (
            b"\x00",
            struct.pack(">B", index & 0xFF),
            struct.pack(">I", max(0, int(position_ms))),
            b"\x00",
            color[:3],
            b"\x00\x00",
            label,
            b"\x00",
        )
    )


def _color_entry_bytes(rgb: bytes = b"\xFF\xFF\xFF") -> bytes:
    return b"\x00" + rgb[:3]


def _bpmlock_entry_bytes(enabled: bool = False) -> bytes:
    return struct.pack("?", bool(enabled))


def _encode_serato32_u24(value: int) -> bytes:
    """3 bajty wartości → 4 bajty serato32 (pozycja ms / RGB)."""
    value = max(0, min(int(value), 0xFFFFFF))
    a = (value >> 16) & 0xFF
    b = (value >> 8) & 0xFF
    c = value & 0xFF
    z = c & 0x7F
    y = ((c >> 7) | (b << 1)) & 0x7F
    x = ((b >> 6) | (a << 2)) & 0x7F
    w = (a >> 5) & 0x07
    return bytes([w, x, y, z])


def _encode_serato32_rgb(rgb: bytes) -> bytes:
    """RGB 3B → serato32 4B."""
    r, g, b = (rgb + b"\x00\x00\x00")[:3]
    return _encode_serato32_u24((r << 16) | (g << 8) | b)


def _rgb_from_loop(lp: LoopPoint, slot: int) -> bytes:
    cp = CuePoint(name=lp.label, pos=0, num=slot + 1, color=lp.color)
    return _rgb_from_cue(cp, slot)


def _loop_entry_id3(start_ms: int, end_ms: int, color: bytes) -> bytes:
    """Wpis loop w formacie ID3/serato32 (Markers_ entry type LOOP=3)."""
    try:
        from serato_tools.track_cues_v1 import TrackCuesV1

        entry = TrackCuesV1.Entry(
            True,
            max(0, int(start_ms)),
            True,
            max(0, int(end_ms)),
            b"\x00\x7f\x7f\x7f\x7f\x7f",
            (color + b"\x00\x00\x00")[:3],
            TrackCuesV1.EntryType.LOOP,
            0,
        )
        return entry.dump()
    except Exception:
        rgb = (color + b"\x00\x00\x00")[:3]
        return b"".join(
            (
                b"\x00",
                _encode_serato32_u24(max(0, int(start_ms))),
                b"\x00",
                _encode_serato32_u24(max(0, int(end_ms))),
                b"\x00\x7f\x7f\x7f\x7f\x7f",
                _encode_serato32_rgb(rgb),
                b"\x03",
                b"\x00",
            )
        )


def _markers_underscore_loop_slot(entry_index: int) -> Optional[int]:
    """Markers_ entries 5–12 → loop slot 0–7."""
    if 5 <= entry_index <= 12:
        return entry_index - 5
    return None


def _markers_payload_is_mp4_format(data: bytes) -> bool:
    """True gdy surowy Markers_ to format MP4 (u32 + 00FFFFFF00), nie ID3/serato32."""
    if len(data) < 26 or data[:2] != b"\x02\x05":
        return False
    mid = data[6 + 8 : 6 + 14]
    return mid == b"\x00\xFF\xFF\xFF\xFF\x00"


def _parse_markers_underscore_loops(raw_payload: bytes) -> list[dict]:
    """Parsuje loopy z payloadu Markers_ (ID3/serato32 albo MP4/u32)."""
    if not raw_payload:
        return []

    if _markers_payload_is_mp4_format(raw_payload):
        loops: list[dict] = []
        try:
            n = struct.unpack(">I", raw_payload[2:6])[0]
        except struct.error:
            return []
        off = 6
        unset = 0xFFFFFFFF
        for idx in range(int(n)):
            if off + 19 > len(raw_payload):
                break
            entry = raw_payload[off : off + 19]
            off += 19
            slot = _markers_underscore_loop_slot(idx)
            if slot is None:
                continue
            start_ms, end_ms = struct.unpack(">II", entry[:8])
            entry_type = entry[17]
            if entry_type != 3:  # LOOP
                continue
            if start_ms == unset or end_ms == unset:
                continue
            if end_ms <= start_ms:
                continue
            loops.append(
                {
                    "slot": slot,
                    "position_ms": int(start_ms),
                    "end_ms": int(end_ms),
                    "color": bytes(entry[14:17]),
                }
            )
        return loops

    try:
        from serato_tools.track_cues_v1 import TrackCuesV1

        v1 = TrackCuesV1(raw_payload)
        entries = getattr(v1, "entries", None) or []
    except Exception:
        return []

    loops = []
    for idx, entry in enumerate(entries):
        slot = _markers_underscore_loop_slot(idx)
        if slot is None:
            continue
        try:
            from serato_tools.track_cues_v1 import TrackCuesV1 as _TCV1

            if entry.type != _TCV1.EntryType.LOOP:
                continue
        except Exception:
            continue
        if not getattr(entry, "start_position_set", False):
            continue
        if not getattr(entry, "end_position_set", False):
            continue
        try:
            start_ms = int(entry.start_position or 0)
            end_ms = int(entry.end_position or 0)
        except (TypeError, ValueError):
            continue
        if end_ms <= start_ms:
            continue
        color = getattr(entry, "color", b"")
        loops.append(
            {
                "slot": slot,
                "position_ms": start_ms,
                "end_ms": end_ms,
                "color": color,
            }
        )
    return loops


def read_markers_underscore_loops_from_file(path: str) -> list[dict]:
    """Odczyt loopów z GEOB Serato Markers_ (wpisy 5–12, typ LOOP)."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    ext = file_path.suffix.lower()
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        from mutagen.aiff import AIFF
        from mutagen.mp4 import MP4
        from mutagen.wave import WAVE
    except ImportError:
        return []

    raw_payload: bytes = b""
    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(file_path))
            except ID3NoHeaderError:
                return []
            geob = tags.get("GEOB:Serato Markers_")
            if geob is None:
                return []
            raw_payload = geob.data
        elif ext in (".aiff", ".aif", ".wav"):
            audio = AIFF(str(file_path)) if ext != ".wav" else WAVE(str(file_path))
            if not audio.tags:
                return []
            geob = audio.tags.get("GEOB:Serato Markers_")
            if geob is None:
                return []
            raw_payload = geob.data
        elif ext in (".m4a", ".mp4"):
            audio = MP4(str(file_path))
            key = "----:com.serato.dj:markers"
            if key not in audio:
                return []
            raw_payload = _mp4_decode_serato_atom(audio[key][0])
        else:
            return []
    except Exception:
        return []

    return _parse_markers_underscore_loops(raw_payload)


def markers_underscore_dicts_to_loops(items: list[dict]) -> list[LoopPoint]:
    """Markers_ loop dict → LoopPoint."""
    out: list[LoopPoint] = []
    used: set[int] = set()
    for item in items or []:
        try:
            slot = int(item.get("slot", -1))
        except (TypeError, ValueError):
            continue
        if slot < 0 or slot > 7 or slot in used:
            continue
        try:
            start_ms = int(item.get("position_ms") or 0)
            end_ms = int(item.get("end_ms") or 0)
        except (TypeError, ValueError):
            continue
        if end_ms <= start_ms:
            continue
        used.add(slot)
        color = None
        raw_col = item.get("color")
        if isinstance(raw_col, (bytes, bytearray)) and len(raw_col) >= 3:
            color = (raw_col[0] << 16) | (raw_col[1] << 8) | raw_col[2]
        out.append(
            LoopPoint(
                slot=slot,
                label=f"Loop {slot + 1}",
                position_ms=start_ms,
                end_ms=end_ms,
                color=color,
            )
        )
    return out


def read_loops_from_file(path: str) -> list[LoopPoint]:
    return markers_underscore_dicts_to_loops(read_markers_underscore_loops_from_file(path))


def encode_serato_markers_underscore(
    cue_points: list[CuePoint],
    loops: Optional[list[LoopPoint]] = None,
) -> bytes:
    """
    Payload „Serato Markers_” w formacie ID3/GEOB (MP3/AIFF/WAV):
    serato32 pozycje/kolory, footer 07 7f 7f 7f.
    """
    by_slot: dict[int, CuePoint] = {}
    for cp in normalize_serato_cue_points(cue_points):
        slot = serato_cue_index(int(cp.num))
        if slot is None or slot > 4:
            continue
        if slot not in by_slot:
            by_slot[slot] = cp

    by_loop: dict[int, LoopPoint] = {}
    for lp in loops or []:
        if 0 <= int(lp.slot) <= 7 and lp.slot not in by_loop:
            if lp.end_ms > lp.position_ms:
                by_loop[int(lp.slot)] = lp

    out = bytearray()
    out += b"\x02\x05"
    out += struct.pack(">I", 14)

    def _empty_entry(entry_type: int = 3) -> bytes:
        return b"".join(
            (
                b"\x7f",
                b"\x7f\x7f\x7f\x7f",
                b"\x7f",
                b"\x7f\x7f\x7f\x7f",
                b"\x00\x7f\x7f\x7f\x7f\x7f",
                b"\x00\x00\x00\x00",
                bytes([entry_type & 0xFF]),
                b"\x00",
            )
        )

    for slot in range(5):
        cp = by_slot.get(slot)
        if not cp:
            # Pusty hot cue 0–4 → INVALID (0); Serato inaczej może ignorować Markers2.
            out += _empty_entry(0)
            continue
        pos_ms = max(0, int(round(float(cp.pos) * 1000.0)))
        color = _rgb_from_cue(cp, slot)
        out += b"".join(
            (
                b"\x00",
                _encode_serato32_u24(pos_ms),
                b"\x7f",
                b"\x7f\x7f\x7f\x7f",
                b"\x00\x7f\x7f\x7f\x7f\x7f",
                _encode_serato32_rgb(color),
                b"\x01",
                b"\x00",
            )
        )

    for slot in range(8):
        lp = by_loop.get(slot)
        if lp:
            out += _loop_entry_id3(
                lp.position_ms,
                lp.end_ms,
                _rgb_from_loop(lp, slot),
            )
        else:
            out += _empty_entry(3)
    # Serato Markers_ ma 9. slot loop (index 13) — pozostaw pusty
    out += _empty_entry(3)

    out += b"\x07\x7f\x7f\x7f"
    return bytes(out)


def encode_serato_markers_mp4(
    cue_points: list[CuePoint],
    loops: Optional[list[LoopPoint]] = None,
) -> bytes:
    """
    Payload „Serato Markers_” dla M4A/MP4 (triseratops write_markers_mp4).

    Inny niż ID3: pozycje jako zwykłe u32 BE (0xFFFFFFFF = puste),
    kolor RGB 3 B (bez serato32), pole środkowe 00FFFFFF00,
    pusty cue = typ 0 (Invalid), footer: \\0 + RGB track color.
    """
    by_slot: dict[int, CuePoint] = {}
    for cp in normalize_serato_cue_points(cue_points):
        slot = serato_cue_index(int(cp.num))
        if slot is None or slot > 4:
            continue
        if slot not in by_slot:
            by_slot[slot] = cp

    by_loop: dict[int, LoopPoint] = {}
    for lp in loops or []:
        if 0 <= int(lp.slot) <= 7 and lp.slot not in by_loop:
            if lp.end_ms > lp.position_ms:
                by_loop[int(lp.slot)] = lp

    unset = b"\xFF\xFF\xFF\xFF"
    mid = b"\x00\xFF\xFF\xFF\xFF\x00"

    def _entry(
        start_ms: Optional[int],
        end_ms: Optional[int],
        color: bytes,
        entry_type: int,
    ) -> bytes:
        start = unset if start_ms is None else struct.pack(">I", max(0, int(start_ms)))
        end = unset if end_ms is None else struct.pack(">I", max(0, int(end_ms)))
        rgb = (color + b"\x00\x00\x00")[:3]
        return b"".join((start, end, mid, rgb, bytes([entry_type & 0xFF]), b"\x00"))

    out = bytearray()
    out += b"\x02\x05"
    out += struct.pack(">I", 14)

    for slot in range(5):
        cp = by_slot.get(slot)
        if not cp:
            # unset cue → typ Invalid (0)
            out += _entry(None, None, b"\x00\x00\x00", 0)
            continue
        pos_ms = max(0, int(round(float(cp.pos) * 1000.0)))
        out += _entry(pos_ms, None, _rgb_from_cue(cp, slot), 1)

    for slot in range(8):
        lp = by_loop.get(slot)
        if lp:
            out += _entry(
                lp.position_ms,
                lp.end_ms,
                _rgb_from_loop(lp, slot),
                3,
            )
        else:
            out += _entry(None, None, b"\x00\x00\x00", 3)
    out += _entry(None, None, b"\x00\x00\x00", 3)

    # footer: null + track color RGB
    out += b"\x00\xFF\xFF\xFF"
    return bytes(out)


def _mp4_serato_atom_payload(serato_name: str, data: bytes, *, with_newlines: bool) -> bytes:
    """
    MP4/FLAC envelope (Holzhaus): base64 bez paddingu z
    application/octet-stream\\0\\0{Serato Name}\\0{data}.
    markers / markersv2: newline co 72 znaki.
    """
    inner = (
        b"application/octet-stream\x00\x00"
        + serato_name.encode("ascii")
        + b"\x00"
        + data
    )
    b64 = base64.b64encode(inner).decode("ascii").rstrip("=")
    if with_newlines:
        b64 = "\n".join(b64[i : i + 72] for i in range(0, len(b64), 72))
    return b64.encode("ascii")


def _mp4_decode_serato_atom(raw: bytes) -> bytes:
    """Dekoduje atom MP4 → surowy payload Serato (Markers_ / Markers2)."""
    if isinstance(raw, str):
        text = raw
    else:
        text = raw.decode("ascii", errors="ignore")
    text = text.replace("\n", "").strip()
    if not text:
        return b""
    pad = "=" * (-len(text) % 4)
    try:
        blob = base64.b64decode(text + pad)
    except Exception:
        return b""
    # Envelope FLAC/MP4: application/octet-stream\\0\\0Name\\0 + data
    prefix = b"application/octet-stream\x00"
    if blob.startswith(prefix):
        rest = blob[len(prefix) :]
        # opcjonalne puste pole (\\0) + nazwa\\0
        if rest.startswith(b"\x00"):
            rest = rest[1:]
        nul = rest.find(b"\x00")
        if nul >= 0:
            return rest[nul + 1 :]
        return rest
    return blob


def _m4a_markers_atom_is_mp4_format(raw: bytes) -> bool:
    """
    True gdy payload Markers_ to format MP4 (u32 + 00FFFFFF00), nie ID3/serato32.
    """
    return _markers_payload_is_mp4_format(_mp4_decode_serato_atom(raw))


def build_markers2_entries(cue_points: list[CuePoint]) -> list[tuple[str, bytes]]:
    """Lista (nazwa_wpisu, payload) do Markers2."""
    entries: list[tuple[str, bytes]] = [
        ("COLOR", _color_entry_bytes()),
    ]
    used: set[int] = set()
    for cp in normalize_serato_cue_points(cue_points):
        slot = serato_cue_index(int(cp.num))
        if slot is None or slot in used:
            continue
        used.add(slot)
        pos_ms = max(0, int(round(float(cp.pos) * 1000.0)))
        color = _rgb_from_cue(cp, slot)
        label = (cp.name or f"Cue {slot + 1}").strip()
        entries.append(("CUE", _cue_entry_bytes(slot, pos_ms, color, label)))
    entries.append(("BPMLOCK", _bpmlock_entry_bytes(False)))
    return entries


def encode_markers2_id3(cue_points: list[CuePoint]) -> bytes:
    """
    Bajtowy tag GEOB „Serato Markers2” (MP3 / AIFF / WAV).
    Zgodny z Holzhaus/serato-tags dump().
    """
    version = struct.pack("BB", 0x01, 0x01)
    parts = [version]
    for name, payload in build_markers2_entries(cue_points):
        parts.append(name.encode("ascii") + b"\x00")
        parts.append(struct.pack(">I", len(payload)))
        parts.append(payload)
    inner = b"".join(parts)

    b64 = bytearray(base64.b64encode(inner).replace(b"=", b"A"))
    i = 72
    while i < len(b64):
        b64.insert(i, 0x0A)
        i += 73

    data = version + bytes(b64)
    if len(data) < 470:
        data = data.ljust(470, b"\x00")
    return data


def encode_markers2_flac_inner(cue_points: list[CuePoint]) -> bytes:
    """Wewnętrzny payload Markers2 (przed base64) — do FLAC/OGG."""
    version = struct.pack("BB", 0x01, 0x01)
    parts = [version]
    for name, payload in build_markers2_entries(cue_points):
        parts.append(name.encode("ascii") + b"\x00")
        parts.append(struct.pack(">I", len(payload)))
        parts.append(payload)
    parts.append(b"\x00")
    return b"".join(parts)


def parse_markers2_id3(data: bytes) -> list[dict]:
    """Parsuje GEOB Serato Markers2 → lista cue dict (index, position_ms, name, color)."""
    if len(data) < 4 or data[0:2] != b"\x01\x01":
        return []
    null_at = data.find(b"\x00", 2)
    if null_at < 0:
        null_at = len(data)
    b64 = data[2:null_at].replace(b"\n", b"")
    pad = b"A==" if len(b64) % 4 == 1 else (b"=" * (-len(b64) % 4))
    try:
        payload = base64.b64decode(b64 + pad)
    except Exception:
        return []
    return _parse_markers2_payload(payload)


def parse_markers2_flac_b64(b64: str) -> list[dict]:
    """Parsuje SERATO_MARKERS_V2 (base64 wewnętrznego payloadu)."""
    raw = (b64 or "").replace("\n", "").strip()
    if not raw:
        return []
    pad = "=" * (-len(raw) % 4)
    try:
        payload = base64.b64decode(raw + pad)
    except Exception:
        return []
    return _parse_markers2_payload(payload)


def _parse_markers2_payload(payload: bytes) -> list[dict]:
    if len(payload) < 2 or payload[0:2] != b"\x01\x01":
        return []
    fp_data = payload[2:]
    cues: list[dict] = []
    pos = 0
    while pos < len(fp_data):
        if fp_data[pos] == 0:
            break
        end = fp_data.find(b"\x00", pos)
        if end < 0:
            break
        name = fp_data[pos:end].decode("ascii", errors="replace")
        pos = end + 1
        if pos + 4 > len(fp_data):
            break
        (entry_len,) = struct.unpack(">I", fp_data[pos : pos + 4])
        pos += 4
        chunk = fp_data[pos : pos + entry_len]
        pos += entry_len
        if name == "CUE" and len(chunk) >= 13:
            index = chunk[1]
            (position_ms,) = struct.unpack(">I", chunk[2:6])
            color = chunk[7:10]
            label = chunk[12:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            cues.append(
                {
                    "index": index,
                    "position_ms": position_ms,
                    "name": label,
                    "color": color,
                }
            )
    return cues


def loops_signature(loops: list[LoopPoint]) -> tuple:
    """Sygnatura loopów do porównania (slot, start_ms, end_ms)."""
    return tuple(
        sorted(
            (
                int(lp.slot),
                max(0, int(lp.position_ms)),
                max(0, int(lp.end_ms)),
            )
            for lp in (loops or [])
            if max(0, int(lp.end_ms)) > max(0, int(lp.position_ms))
            and 0 <= int(lp.slot) <= 7
        )
    )


def parsed_loops_signature(parsed: list[dict]) -> tuple:
    return loops_signature(
        [
            LoopPoint(
                slot=int(p.get("slot", 0)),
                label="",
                position_ms=int(p.get("position_ms") or 0),
                end_ms=int(p.get("end_ms") or 0),
            )
            for p in (parsed or [])
        ]
    )


def track_has_exportable_markers(track: Track) -> bool:
    """Hot cues (1–8, z remapem nadmiaru) i/lub loop sloty 0–7."""
    if normalize_serato_cue_points(track.cue_points or []):
        return True
    return bool(loops_signature(track.loops or []))


def cue_points_signature(cue_points: list[CuePoint]) -> tuple:
    """Sygnatura hot cues do porównania (index, ms, name) — bez koloru."""
    used: set[int] = set()
    out: list[tuple] = []
    for cp in normalize_serato_cue_points(cue_points):
        slot = serato_cue_index(int(cp.num))
        if slot is None or slot in used:
            continue
        used.add(slot)
        pos_ms = max(0, int(round(float(cp.pos) * 1000.0)))
        label = (cp.name or f"Cue {slot + 1}").strip()
        out.append((slot, pos_ms, label))
    return tuple(out)


def parsed_cues_signature(parsed: list[dict]) -> tuple:
    return tuple(
        sorted(
            (
                int(p.get("index", 0)),
                int(p.get("position_ms", 0)),
                str(p.get("name") or ""),
            )
            for p in (parsed or [])
        )
    )


def read_markers2_cues_from_file(path: str) -> list[dict]:
    """Odczyt istniejących hot cues Markers2 z pliku (pusta lista = brak / błąd)."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    ext = file_path.suffix.lower()
    try:
        from mutagen.aiff import AIFF
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3, ID3NoHeaderError
        from mutagen.mp4 import MP4
        from mutagen.wave import WAVE
    except ImportError:
        return []

    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(file_path))
            except ID3NoHeaderError:
                return []
            geob = tags.get("GEOB:Serato Markers2")
            if geob is None:
                return []
            return parse_markers2_id3(geob.data)

        if ext in (".aiff", ".aif", ".wav"):
            audio = AIFF(str(file_path)) if ext != ".wav" else WAVE(str(file_path))
            if not audio.tags:
                return []
            geob = audio.tags.get("GEOB:Serato Markers2")
            if geob is None:
                return []
            return parse_markers2_id3(geob.data)

        if ext == ".flac":
            audio = FLAC(str(file_path))
            vals = audio.get("SERATO_MARKERS_V2") or audio.get("serato_markers2") or []
            if not vals:
                return []
            return parse_markers2_flac_b64(str(vals[0]))

        if ext in (".m4a", ".mp4"):
            audio = MP4(str(file_path))
            key = "----:com.serato.dj:markersv2"
            if key not in audio:
                return []
            blob = _mp4_decode_serato_atom(audio[key][0])
            if not blob:
                return []
            return parse_markers2_id3(blob)
    except Exception:
        return []
    return []


def enrich_tracks_with_serato_loops(
    tracks: list[Track],
    *,
    max_workers: int = 8,
) -> dict:
    """
    Dopisuje loops z Markers_ w plikach audio (równolegle).
    Zwraca {with_loops, scanned, missing_file}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    stats = {"with_loops": 0, "scanned": 0, "missing_file": 0}
    if not tracks:
        return stats

    def _one(idx: int, path: str) -> tuple[int, list[LoopPoint]]:
        if not path or not Path(path).is_file():
            return idx, []
        return idx, read_loops_from_file(path)

    jobs: list[tuple[int, str]] = []
    for i, t in enumerate(tracks):
        if t.loops:
            stats["with_loops"] += 1
            continue
        p = (t.path or "").strip()
        if not p:
            continue
        if not Path(p).is_file():
            stats["missing_file"] += 1
            continue
        jobs.append((i, p))

    if not jobs:
        return stats

    workers = max(1, min(max_workers, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, i, p) for i, p in jobs]
        for fut in as_completed(futs):
            idx, lps = fut.result()
            stats["scanned"] += 1
            if not lps:
                continue
            tracks[idx].loops = lps
            stats["with_loops"] += 1
    return stats


def enrich_tracks_with_serato_file_markers(
    tracks: list[Track],
    *,
    max_workers: int = 8,
) -> dict:
    """Hot cues (Markers2) + loop (Markers_) z plików audio."""
    cue_stats = enrich_tracks_with_serato_markers2(tracks, max_workers=max_workers)
    loop_stats = enrich_tracks_with_serato_loops(tracks, max_workers=max_workers)
    return {"cues": cue_stats, "loops": loop_stats}


def markers2_dicts_to_cue_points(cues: list[dict]) -> list[CuePoint]:
    """Markers2 dict (index 0–7, position_ms) → CuePoint (num 1–8, pos sekundy)."""
    out: list[CuePoint] = []
    used: set[int] = set()
    for c in cues or []:
        try:
            idx = int(c.get("index", -1))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx > 7 or idx in used:
            continue
        used.add(idx)
        try:
            pos_ms = int(c.get("position_ms") or 0)
        except (TypeError, ValueError):
            continue
        if pos_ms < 0:
            continue
        label = (c.get("name") or f"Cue {idx + 1}").strip() or f"Cue {idx + 1}"
        color = None
        raw_col = c.get("color")
        if isinstance(raw_col, (bytes, bytearray)) and len(raw_col) >= 3:
            color = (raw_col[0] << 16) | (raw_col[1] << 8) | raw_col[2]
        out.append(
            CuePoint(
                name=label[:64],
                pos=pos_ms / 1000.0,
                num=idx + 1,
                color=color,
            )
        )
    return out


def markers_underscore_has_low_slots(path: str, cue_points: list[CuePoint]) -> bool:
    """
    True gdy Markers_ ma ustawione wszystkie hot cue na slotach 0–4 z cue_points.
    Serato bierze pady 1–5 głównie z Markers_ — sam Markers2 nie wystarczy.
    """
    wanted = {
        serato_cue_index(int(cp.num))
        for cp in (cue_points or [])
        if serato_cue_index(int(cp.num)) is not None
        and serato_cue_index(int(cp.num)) <= 4
    }
    if not wanted:
        return True
    try:
        from serato_tools.track_cues_v1 import TrackCuesV1

        v1 = TrackCuesV1(str(path))
        entries = getattr(v1, "entries", None) or []
        for slot in wanted:
            if slot >= len(entries):
                return False
            if not getattr(entries[slot], "start_position_set", False):
                return False
        return True
    except Exception:
        # Bez serato_tools: brak GEOB Markers_ = niekompletne
        try:
            from mutagen.id3 import ID3, ID3NoHeaderError

            tags = ID3(str(path))
            geob = tags.get("GEOB:Serato Markers_")
            return geob is not None and len(geob.data or b"") > 20
        except Exception:
            return False


def merge_track_markers_with_file(track: Track, path: Optional[str] = None) -> Track:
    """
    Uzupełnia brakujące cue/loopy w Track danymi z pliku audio.

    Zapis Markers2+Markers_ zawsze nadpisuje OBA tagi — bez merge zapis
    samych loopów wymazuje cue (i odwrotnie). VDJ/źródło wygrywa, gdy
    dana strona jest już wypełniona w Track.
    """
    p = path or track.path
    if not p or _is_streaming_path(p) or not Path(p).is_file():
        return track

    cues = list(track.cue_points or [])
    loops = list(track.loops or [])

    if not cues:
        cues = markers2_dicts_to_cue_points(read_markers2_cues_from_file(p))
    if not loops:
        loops = list(read_loops_from_file(p) or [])

    if cues is track.cue_points and loops is track.loops:
        return track
    if cues == (track.cue_points or []) and loops == (track.loops or []):
        return track

    return Track(
        path=track.path,
        title=track.title,
        artist=track.artist,
        album=track.album,
        genre=track.genre,
        tags=list(track.tags or []),
        comment=track.comment,
        bpm=track.bpm,
        key=track.key,
        year=track.year,
        duration=track.duration,
        play_count=track.play_count,
        rating=track.rating,
        beatgrid=list(track.beatgrid or []),
        cue_points=cues,
        loops=loops,
        source_id=track.source_id,
    )


def repair_markers_underscore_from_markers2(path: str) -> tuple[bool, str]:
    """Przepisuje Markers_ (+Markers2) z istniejących cue w Markers2; zachowuje loopy z pliku."""
    cues = read_markers2_cues_from_file(path)
    if not cues:
        return False, "NO_MARKERS2"
    cps = markers2_dicts_to_cue_points(cues)
    if not cps:
        return False, "NO_CUES"
    existing_loops = list(read_loops_from_file(path) or [])
    track = Track(
        path=path,
        title="",
        artist="",
        cue_points=cps,
        loops=existing_loops,
    )
    return write_serato_markers2_to_file(
        track, path, skip_unchanged=False, preserve_existing=False
    )


def enrich_tracks_with_serato_markers2(
    tracks: list[Track],
    *,
    max_workers: int = 8,
) -> dict:
    """
    Dopisuje cue_points z Markers2 w plikach audio (równolegle).
    Zwraca {with_cues, scanned, missing_file}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    stats = {"with_cues": 0, "scanned": 0, "missing_file": 0}
    if not tracks:
        return stats

    def _one(idx: int, path: str) -> tuple[int, list[CuePoint]]:
        if not path or not Path(path).is_file():
            return idx, []
        return idx, markers2_dicts_to_cue_points(read_markers2_cues_from_file(path))

    jobs: list[tuple[int, str]] = []
    for i, t in enumerate(tracks):
        if t.cue_points:
            stats["with_cues"] += 1
            continue
        p = (t.path or "").strip()
        if not p:
            continue
        if not Path(p).is_file():
            stats["missing_file"] += 1
            continue
        jobs.append((i, p))

    if not jobs:
        return stats

    workers = max(1, min(max_workers, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, i, p) for i, p in jobs]
        for fut in as_completed(futs):
            idx, cps = fut.result()
            stats["scanned"] += 1
            if not cps:
                continue
            tracks[idx].cue_points = cps
            stats["with_cues"] += 1
    return stats


def write_serato_markers2_to_file(
    track: Track,
    path: Optional[str] = None,
    *,
    skip_unchanged: bool = True,
    preserve_existing: bool = True,
) -> tuple[bool, str]:
    """
    Zapisuje hot cues (+ loopy) utworu do pliku audio (Markers2 + Markers_).
    skip_unchanged: True = nie nadpisuj, gdy istniejące cue/loopy są takie same.
    preserve_existing: True = uzupełnij pustą stronę (cue lub loop) z pliku,
    żeby zapis samych loopów nie wymazywał cue i odwrotnie.
    Zwraca (sukces, komunikat). STREAMING_SKIP / UNCHANGED / brak cue → False.
    """
    p = path or track.path
    if _is_streaming_path(p):
        return False, "STREAMING_SKIP"

    if preserve_existing:
        track = merge_track_markers_with_file(track, p)

    if not track_has_exportable_markers(track):
        return False, "NO_MARKERS"

    file_path = Path(p)
    if not file_path.is_file():
        return False, f"Plik nie istnieje: {file_path}"

    ext = file_path.suffix.lower()
    if ext not in _SUPPORTED_EXT:
        return False, f"Format nieobsługiwany: {ext}"

    if skip_unchanged:
        wanted_cues = cue_points_signature(track.cue_points)
        wanted_loops = loops_signature(track.loops)
        same_cues = True
        same_loops = True
        if wanted_cues:
            existing = read_markers2_cues_from_file(str(file_path))
            same_cues = bool(
                existing and parsed_cues_signature(existing) == tuple(sorted(wanted_cues))
            )
        if wanted_loops:
            existing_loops = read_markers_underscore_loops_from_file(str(file_path))
            same_loops = parsed_loops_signature(existing_loops) == wanted_loops
        same = same_cues and same_loops
        if wanted_cues and same_cues:
            # M4A/MP4: bez atomu „markers” lub ze złym formatem (ID3/serato32)
            # Serato ignoruje cue 0–4 — wymuś przepisanie
            if ext in (".m4a", ".mp4"):
                try:
                    from mutagen.mp4 import MP4 as _MP4

                    _a = _MP4(str(file_path))
                    if "----:com.serato.dj:markers" not in _a:
                        same = False
                    elif not _m4a_markers_atom_is_mp4_format(_a["----:com.serato.dj:markers"][0]):
                        same = False
                except Exception:
                    same = False
            # MP3/AIFF/WAV: pady 1–5 z Markers_ — sam zgodny Markers2 ≠ OK
            if ext in (".mp3", ".aiff", ".aif", ".wav"):
                if not markers_underscore_has_low_slots(
                    str(file_path), track.cue_points
                ):
                    same = False
        if same and (wanted_cues or wanted_loops):
            return False, "UNCHANGED"

    try:
        from mutagen.aiff import AIFF
        from mutagen.flac import FLAC
        from mutagen.id3 import GEOB, ID3, ID3NoHeaderError
        from mutagen.mp4 import MP4, MP4FreeForm
        from mutagen.wave import WAVE
    except ImportError:
        return False, "Brak mutagen: pip install mutagen"

    def _geob(desc: str, data: bytes) -> GEOB:
        return GEOB(
            encoding=0,
            mime="application/octet-stream",
            desc=desc,
            data=data,
        )

    def _mp4_freeform(payload: bytes) -> list:
        fmt = getattr(MP4FreeForm, "FORMAT_UTF8", None)
        if fmt is not None:
            return [MP4FreeForm(payload, dataformat=fmt)]
        return [MP4FreeForm(payload)]

    try:
        markers_u = encode_serato_markers_underscore(track.cue_points, track.loops)
        markers2 = encode_markers2_id3(track.cue_points)
        markers_mp4 = encode_serato_markers_mp4(track.cue_points, track.loops)

        if ext == ".mp3":
            try:
                tags = ID3(str(file_path))
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("GEOB:Serato Markers2")
            tags.delall("GEOB:Serato Markers_")
            tags.add(_geob("Serato Markers2", markers2))
            tags.add(_geob("Serato Markers_", markers_u))
            tags.save(str(file_path), v2_version=3)
            return True, "OK"

        if ext in (".aiff", ".aif", ".wav"):
            audio = AIFF(str(file_path)) if ext != ".wav" else WAVE(str(file_path))
            if audio.tags is None:
                audio.add_tags()
            audio.tags.delall("GEOB:Serato Markers2")
            audio.tags.delall("GEOB:Serato Markers_")
            audio.tags.add(_geob("Serato Markers2", markers2))
            audio.tags.add(_geob("Serato Markers_", markers_u))
            audio.save()
            return True, "OK"

        if ext == ".flac":
            audio = FLAC(str(file_path))
            # FLAC: base64 wewnętrznego payloadu (jak Mixxx dumpCommon)
            inner = encode_markers2_flac_inner(track.cue_points)
            b64 = base64.b64encode(inner).decode("ascii")
            audio["SERATO_MARKERS_V2"] = [b64]
            audio.save()
            return True, "OK"

        if ext in (".m4a", ".mp4"):
            audio = MP4(str(file_path))
            # Oba atomy wymagane — bez „markers” Serato ignoruje cue 0–4
            # markers = format MP4 (u32), nie ID3/serato32
            audio["----:com.serato.dj:markers"] = _mp4_freeform(
                _mp4_serato_atom_payload(
                    "Serato Markers_", markers_mp4, with_newlines=True
                )
            )
            audio["----:com.serato.dj:markersv2"] = _mp4_freeform(
                _mp4_serato_atom_payload(
                    "Serato Markers2", markers2, with_newlines=True
                )
            )
            audio.save()
            return True, "OK"

        return False, f"Format nieobsługiwany: {ext}"
    except Exception as e:
        return False, str(e)


def write_serato_markers2_batch(
    tracks: list[Track],
    path_resolver=None,
    *,
    skip_unchanged: bool = True,
    workers: int = 6,
    progress_cb=None,
) -> tuple[int, int, int, int, list[str]]:
    """
    Zapis Markers2 dla listy utworów (równolegle).
    Zwraca: (written, skipped, unchanged, failed, errors[:]).
    progress_cb(done, total, written, unchanged) — opcjonalnie.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    written = skipped = unchanged = failed = 0
    errors: list[str] = []
    total = len(tracks)
    if total == 0:
        return 0, 0, 0, 0, []

    def _one(t: Track) -> tuple[str, bool, str]:
        path = path_resolver(t) if path_resolver else t.path
        try:
            ok, msg = write_serato_markers2_to_file(
                t, path, skip_unchanged=skip_unchanged
            )
            return path, ok, msg
        except Exception as e:
            return path, False, str(e)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 12))) as ex:
        futs = [ex.submit(_one, t) for t in tracks]
        for fut in as_completed(futs):
            path, ok, msg = fut.result()
            done += 1
            if ok:
                written += 1
            elif msg == "UNCHANGED":
                unchanged += 1
            elif msg in ("STREAMING_SKIP", "NO_CUES", "NO_HOTCUES"):
                skipped += 1
            elif msg.startswith("Plik nie istnieje") or msg.startswith(
                "Format nieobsługiwany"
            ):
                skipped += 1
                if len(errors) < 80:
                    errors.append(f"{Path(path).name}: {msg}")
            else:
                failed += 1
                if len(errors) < 80:
                    errors.append(f"{Path(path).name}: {msg}")
            if progress_cb and (done % 50 == 0 or done == total):
                try:
                    progress_cb(done, total, written, unchanged)
                except Exception:
                    pass
    return written, skipped, unchanged, failed, errors
