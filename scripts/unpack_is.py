#!/usr/bin/env python3
"""Extract InstallShield Unicode plain streams from an InstallShield setup.exe."""

import os
import struct
import sys


SIGNATURE = "Disk1\\".encode("utf-16le")


def find_stream_start(f) -> tuple[int, int]:
    """Locate the 4-byte entry count preceding the first Disk1\\ entry."""
    chunk_size = 4 * 1024 * 1024
    overlap = len(SIGNATURE) + 512
    offset = 0
    while True:
        f.seek(offset)
        buf = f.read(chunk_size)
        if not buf:
            break
        idx = buf.find(SIGNATURE)
        if idx != -1:
            sig_pos = offset + idx
            # Read window before signature to locate: <uint32 count><utf16le name>\0\0Disk1\
            win_start = max(0, sig_pos - 512)
            f.seek(win_start)
            window = f.read(sig_pos - win_start)
            # The byte pair right before Disk1\ must be \x00\x00 (end of `name`)
            if len(window) >= 6 and window[-2:] == b"\x00\x00":
                # Walk backwards in 2-byte UTF-16LE steps through `name`
                pos = len(window) - 4
                while pos >= 4:
                    code_unit = struct.unpack("<H", window[pos : pos + 2])[0]
                    if not (0x20 <= code_unit <= 0x7E):
                        break
                    pos -= 2
                count_pos = win_start + pos - 2
                f.seek(count_pos)
                count = struct.unpack("<I", f.read(4))[0]
                if 1 <= count <= 10000:
                    return count_pos, count
            offset = sig_pos + len(SIGNATURE)
            continue
        if len(buf) < chunk_size:
            break
        offset += chunk_size - overlap
    raise RuntimeError("Could not find InstallShield Disk1\\ stream header.")


def read_wstr(f) -> str:
    """Read a null-terminated UTF-16LE string from a binary file."""
    chars = bytearray()
    while True:
        c = f.read(2)
        if len(c) < 2 or c == b"\x00\x00":
            break
        chars.extend(c)
    return chars.decode("utf-16le", errors="replace")


def unpack_stream(exe_path: str, out_dir: str) -> None:
    """Unpack all embedded InstallShield files from exe_path into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    file_size = os.path.getsize(exe_path)
    with open(exe_path, "rb") as f:
        count_pos, count = find_stream_start(f)
        print(f"Found {count} entries starting at offset {count_pos}")
        f.seek(count_pos + 4)
        for i in range(count):
            name = read_wstr(f)
            disk_path = read_wstr(f)
            version = read_wstr(f)
            size_str = read_wstr(f)
            size = int(size_str) if size_str.isdigit() else 0
            data_offset = f.tell()
            if data_offset + size > file_size:
                raise RuntimeError(
                    f"Entry [{i}] {name} exceeds file size ({data_offset} + {size} > {file_size})"
                )
            safe_name = os.path.basename(name.replace("\\", "/"))
            dest_path = os.path.join(out_dir, safe_name)
            print(f"[{i}] {safe_name} ({disk_path}, v{version}, {size} bytes)")
            remaining = size
            with open(dest_path, "wb") as out_f:
                while remaining > 0:
                    chunk = f.read(min(remaining, 8 * 1024 * 1024))
                    if not chunk:
                        raise RuntimeError(f"Unexpected EOF reading {safe_name}")
                    out_f.write(chunk)
                    remaining -= len(chunk)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <installer.exe> <output_dir>", file=sys.stderr)
        return 1
    unpack_stream(sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
