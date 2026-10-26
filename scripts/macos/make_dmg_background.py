"""Tło okna DMG: biała plansza i strzałka między ikoną programu a folderem Aplikacje."""
import struct
import zlib
from pathlib import Path

W, H = 540, 380


def pixel(x: int, y: int) -> bytes:
    # Strzałka w poziomie ikon (x 210–330, y około 186).
    if 214 <= x <= 300 and 183 <= y <= 189:
        return b"\xb4\xb4\xb4\xff"
    if 300 <= x <= 328 and abs(y - 186) <= (328 - x) * 0.55:
        return b"\xb4\xb4\xb4\xff"
    return b"\xff\xff\xff\xff"


def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def main() -> None:
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        for x in range(W):
            raw.extend(pixel(x, y))
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    out = Path(__file__).with_name("dmg-background.png")
    out.write_bytes(png)


if __name__ == "__main__":
    main()
