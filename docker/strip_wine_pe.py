#!/usr/bin/env python3
"""Strip DWARF debug sections from Wine builtin PE modules and matching prefix copies."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

PE_EXTS = {".dll", ".exe", ".drv", ".cpl", ".ocx", ".sys", ".acm", ".ax"}
BUILTIN_SIG = b"Wine builtin DLL"

WINE_PREFIX_PAIRS = (
    (Path("/usr/lib/x86_64-linux-gnu/wine/x86_64-windows"), Path("drive_c/windows/system32")),
    (Path("/usr/lib/x86_64-linux-gnu/wine/i386-windows"), Path("drive_c/windows/syswow64")),
)


def strip_wine_dir(wine_dir: Path, td_path: Path) -> tuple[dict[str, tuple[str, bytes]], int, int]:
    """Strip Wine builtin PE files in `wine_dir` and return {name: (orig_sha256, new_bytes)}."""
    if not wine_dir.is_dir():
        return {}, 0, 0

    candidates: list[tuple[Path, str, bytes]] = []
    work_dir = td_path / wine_dir.name
    work_dir.mkdir(parents=True, exist_ok=True)

    for wf in wine_dir.iterdir():
        if not wf.is_file() or wf.is_symlink() or wf.suffix.lower() not in PE_EXTS:
            continue
        raw = wf.read_bytes()
        if BUILTIN_SIG not in raw[:512]:
            continue
        orig_sha = hashlib.sha256(raw).hexdigest()
        (work_dir / wf.name).write_bytes(raw)
        candidates.append((wf, orig_sha, raw))

    work_files = [str(work_dir / wf.name) for wf, _, _ in candidates]
    for i in range(0, len(work_files), 200):
        subprocess.run(["strip", "--strip-debug", *work_files[i : i + 200]], check=True)

    result: dict[str, tuple[str, bytes]] = {}
    stripped_count = 0
    saved_bytes = 0
    for wf, orig_sha, orig_raw in candidates:
        new_raw = (work_dir / wf.name).read_bytes()
        if BUILTIN_SIG in new_raw[:512] and len(new_raw) < len(orig_raw):
            wf.write_bytes(new_raw)
            result[wf.name] = (orig_sha, new_raw)
            stripped_count += 1
            saved_bytes += len(orig_raw) - len(new_raw)

    return result, stripped_count, saved_bytes


def sync_prefix_dir(prefix_dir: Path, stripped_map: dict[str, tuple[str, bytes]]) -> tuple[int, int]:
    """Replace Wine builtin copies in `prefix_dir` only when byte-identical to unstripped originals."""
    if not prefix_dir.is_dir():
        return 0, 0

    replaced = 0
    saved = 0
    for pf in prefix_dir.iterdir():
        if not pf.is_file() or pf.is_symlink() or pf.name not in stripped_map:
            continue
        orig_sha, new_raw = stripped_map[pf.name]
        pf_raw = pf.read_bytes()
        if hashlib.sha256(pf_raw).hexdigest() == orig_sha:
            pf.write_bytes(new_raw)
            replaced += 1
            saved += len(pf_raw) - len(new_raw)
    return replaced, saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, help="Optional Wine prefix root to deduplicate stripped builtins into.")
    args = parser.parse_args()

    total_wine_stripped = 0
    total_wine_saved = 0
    total_prefix_replaced = 0
    total_prefix_saved = 0

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        for wine_dir, rel_prefix_dir in WINE_PREFIX_PAIRS:
            stripped_map, cnt, saved = strip_wine_dir(wine_dir, td_path)
            total_wine_stripped += cnt
            total_wine_saved += saved
            if args.prefix is not None:
                rep, rep_saved = sync_prefix_dir(args.prefix / rel_prefix_dir, stripped_map)
                total_prefix_replaced += rep
                total_prefix_saved += rep_saved

    print(f"[wine-strip] stripped {total_wine_stripped} Wine PE modules, saved {total_wine_saved / 1e6:.1f} MB")

    if args.prefix is not None:
        fonts_dir = args.prefix / "drive_c" / "windows" / "Fonts"
        if fonts_dir.exists():
            for entry in fonts_dir.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
        else:
            fonts_dir.mkdir(parents=True, exist_ok=True)
        (args.prefix / "drive_c" / "ScanSnapHome").mkdir(parents=True, exist_ok=True)
        print(f"[prefix-prep] replaced {total_prefix_replaced} Wine builtins, saved {total_prefix_saved / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
