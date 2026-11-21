#!/usr/bin/env python3
"""
Generate 100% open-source (SIL OFL) TTF font substitutes for Wine/WPF at build time.

Produces hinted TrueType families with DirectWrite/ClearType-friendly `gasp`
tables from Ubuntu's `fonts-noto-core` + `ttfautohint` and `fonts-liberation`.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

TARGET_GASP_TABLE = struct.pack(">HHHH", 1, 1, 65535, 0x000F)

NOTO_DIR = Path("/usr/share/fonts/truetype/noto")
LIBERATION_DIR = Path("/usr/share/fonts/truetype/liberation")

# (source_base_dir, src_prefix, src_family, src_ps, target_family, target_ps, hint_noto, variants)
FONT_SPECS = [
    (
        NOTO_DIR,
        "NotoSans",
        "Noto Sans",
        "NotoSans",
        "Segoe UI",
        "SegoeUI",
        True,
        [("Regular", "segoeui.ttf"), ("Bold", "segoeuib.ttf"), ("Italic", "segoeuii.ttf"), ("BoldItalic", "segoeuiz.ttf")],
    ),
    (
        NOTO_DIR,
        "NotoSans",
        "Noto Sans",
        "NotoSans",
        "Tahoma",
        "Tahoma",
        True,
        [("Regular", "tahoma.ttf"), ("Bold", "tahomabd.ttf")],
    ),
    (
        NOTO_DIR,
        "NotoSans",
        "Noto Sans",
        "NotoSans",
        "Meiryo UI",
        "MeiryoUI",
        True,
        [("Regular", "meiryoui.ttf"), ("Bold", "meiryouib.ttf")],
    ),
    (
        NOTO_DIR,
        "NotoSans",
        "Noto Sans",
        "NotoSans",
        "Verdana",
        "Verdana",
        True,
        [("Regular", "verdana.ttf"), ("Bold", "verdanab.ttf"), ("Italic", "verdanai.ttf"), ("BoldItalic", "verdanaz.ttf")],
    ),
    (
        LIBERATION_DIR,
        "LiberationSans",
        "Liberation Sans",
        "LiberationSans",
        "Arial",
        "Arial",
        False,
        [("Regular", "arial.ttf"), ("Bold", "arialbd.ttf"), ("Italic", "ariali.ttf"), ("BoldItalic", "arialbi.ttf")],
    ),
    (
        LIBERATION_DIR,
        "LiberationSerif",
        "Liberation Serif",
        "LiberationSerif",
        "Times New Roman",
        "TimesNewRoman",
        False,
        [("Regular", "times.ttf"), ("Bold", "timesbd.ttf"), ("Italic", "timesi.ttf"), ("BoldItalic", "timesbi.ttf")],
    ),
    (
        LIBERATION_DIR,
        "LiberationMono",
        "Liberation Mono",
        "LiberationMono",
        "Courier New",
        "CourierNew",
        False,
        [("Regular", "cour.ttf"), ("Bold", "courbd.ttf"), ("Italic", "couri.ttf"), ("BoldItalic", "courbi.ttf")],
    ),
]


def calc_sfnt_checksum(data: bytes) -> int:
    """Compute OpenType uint32 big-endian checksum over 4-byte-padded data."""
    rem = len(data) % 4
    if rem:
        data += b"\x00" * (4 - rem)
    total = 0
    for (word,) in struct.iter_unpack(">I", data):
        total = (total + word) & 0xFFFFFFFF
    return total


def parse_sfnt(data: bytes) -> tuple[bytes, list[tuple[bytes, bytes]]]:
    """Parse an SFNT font into its 4-byte version tag and ordered [(tag, payload)]."""
    sfnt_ver = data[:4]
    num_tables = struct.unpack(">H", data[4:6])[0]
    entries = []
    for i in range(num_tables):
        off_rec = 12 + i * 16
        tag = data[off_rec : off_rec + 4]
        offset, length = struct.unpack(">II", data[off_rec + 8 : off_rec + 16])
        entries.append((offset, tag, data[offset : offset + length]))
    entries.sort(key=lambda item: item[0])
    return sfnt_ver, [(tag, payload) for _, tag, payload in entries]


def build_sfnt(sfnt_ver: bytes, tables: list[tuple[bytes, bytes]]) -> bytes:
    """Serialize ordered SFNT tables, updating directory checksums and head adjustment."""
    num_tables = len(tables)
    entry_selector = (num_tables.bit_length() - 1) if num_tables > 0 else 0
    search_range = (1 << entry_selector) * 16
    range_shift = num_tables * 16 - search_range
    header = struct.pack(">4sHHHH", sfnt_ver, num_tables, search_range, entry_selector, range_shift)

    table_map = {tag: payload for tag, payload in tables}
    if b"head" in table_map:
        head_buf = bytearray(table_map[b"head"])
        head_buf[8:12] = b"\x00\x00\x00\x00"
        table_map[b"head"] = bytes(head_buf)

    data_offset = 12 + num_tables * 16
    body_chunks = []
    records = {}
    cur = data_offset
    for tag, _ in tables:
        payload = table_map[tag]
        checksum = calc_sfnt_checksum(payload)
        records[tag] = (checksum, cur, len(payload))
        padded = payload + (b"\x00" * ((4 - (len(payload) % 4)) % 4))
        body_chunks.append(padded)
        cur += len(padded)

    dir_bytes = b"".join(struct.pack(">4sIII", tag, *records[tag]) for tag in sorted(records.keys()))
    out = bytearray(header + dir_bytes + b"".join(body_chunks))

    if b"head" in records:
        _, head_off, _ = records[b"head"]
        whole_sum = calc_sfnt_checksum(bytes(out))
        adj = (0xB1B0AFBA - whole_sum) & 0xFFFFFFFF
        out[head_off + 8 : head_off + 12] = struct.pack(">I", adj)

    return bytes(out)


def rewrite_name_table(
    name_data: bytes,
    src_family: str,
    src_ps: str,
    target_family: str,
    target_ps: str,
) -> bytes:
    """Rebuild an OpenType `name` table replacing source family/PS names with target aliases."""
    _, count, str_off = struct.unpack(">HHH", name_data[:6])
    extra_header = name_data[6 : 6 + count * 12]
    string_blob = name_data[str_off:]

    new_records = []
    new_strings = bytearray()

    for i in range(count):
        pid, eid, lid, nid, slen, soff = struct.unpack(">HHHHHH", extra_header[i * 12 : (i + 1) * 12])
        raw = string_blob[soff : soff + slen]
        enc = "utf-16be" if pid in (0, 3) else "mac_roman"
        text = raw.decode(enc, errors="replace")
        if nid in (1, 3, 4, 6, 16, 17, 21):
            text = text.replace(src_family, target_family).replace(src_ps, target_ps)
        encoded = text.encode(enc, errors="replace")
        new_records.append((pid, eid, lid, nid, len(encoded), len(new_strings)))
        new_strings.extend(encoded)

    hdr = struct.pack(">HHH", 0, len(new_records), 6 + len(new_records) * 12)
    recs = b"".join(struct.pack(">HHHHHH", *r) for r in new_records)
    return hdr + recs + bytes(new_strings)


def prepare_source_fonts(td: Path, use_ttfautohint: bool) -> dict[Path, tuple[bytes, list[tuple[bytes, bytes]]]]:
    """Hint NotoSans sources once via ttfautohint and cache parsed SFNT tables per source TTF."""
    cache: dict[Path, tuple[bytes, list[tuple[bytes, bytes]]]] = {}
    for base_dir, prefix, _, _, _, _, hint_noto, variants in FONT_SPECS:
        for variant, _ in variants:
            src_path = base_dir / f"{prefix}-{variant}.ttf"
            if src_path in cache:
                continue
            if not src_path.exists():
                raise FileNotFoundError(f"Missing open source font: {src_path}")

            read_path = src_path
            if hint_noto and use_ttfautohint:
                hinted = td / f"{src_path.stem}-hinted.ttf"
                subprocess.run(
                    ["ttfautohint", "--windows-compatibility", "--no-info", str(src_path), str(hinted)],
                    check=True,
                )
                read_path = hinted

            cache[src_path] = parse_sfnt(read_path.read_bytes())
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output directory for generated TTFs.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    has_ttfautohint = shutil.which("ttfautohint") is not None

    with tempfile.TemporaryDirectory() as td:
        cache = prepare_source_fonts(Path(td), has_ttfautohint)
        count = 0
        for base_dir, prefix, src_fam, src_ps, dst_fam, dst_ps, _, variants in FONT_SPECS:
            for variant, out_name in variants:
                src_path = base_dir / f"{prefix}-{variant}.ttf"
                sfnt_ver, tables = cache[src_path]
                rebuilt = []
                saw_gasp = False
                for tag, payload in tables:
                    if tag == b"name":
                        payload = rewrite_name_table(payload, src_fam, src_ps, dst_fam, dst_ps)
                    elif tag == b"gasp":
                        payload = TARGET_GASP_TABLE
                        saw_gasp = True
                    rebuilt.append((tag, payload))
                if not saw_gasp:
                    rebuilt.append((b"gasp", TARGET_GASP_TABLE))

                (args.out / out_name).write_bytes(build_sfnt(sfnt_ver, rebuilt))
                count += 1
                print(f"[open-fonts] {out_name} <- {src_path.name} ({dst_fam} {variant})")

    print(f"[open-fonts] generated {count} SIL-OFL font files in {args.out}")


if __name__ == "__main__":
    main()
