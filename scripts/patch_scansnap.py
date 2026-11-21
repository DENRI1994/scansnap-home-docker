#!/usr/bin/env python3
"""
Reusable Linux/Wine compatibility patcher for PFU ScanSnap Home.

Applies and verifies all patches required to run ScanSnap Home cleanly in Wine /
Docker across updates and container restarts:
  1. Clears `${WINEPREFIX}/drive_c/windows/Fonts` so Wine/WPF discovers external
     Fontconfig open-source TTF aliases (`Segoe UI`, `Tahoma`, `Meiryo UI`, `Arial`, ...).
  2. Patches `.NET System.ServiceModel.dll` (`NetNamedPipeBinding` default
     security mode `Transport` -> `None`) and clears stale NGEN native images.
  3. Ensures all `ScanSnap/Home/*.config` `<netNamedPipeBinding>` entries
     declare `<security mode="None" />` (healed after ScanSnap Home updates).
  4. Patches `ScanSnap/Update/SsUCommon.dll` so `ScanSnapUpdater.exe` reports
     OS `10.0` instead of clamped `6.2` under Wine.
  5. Patches `ScanSnap/Update/ScanSnapUpdater.exe` to load `SsUUACBridge.dll`
     via `CoCreateInstance(..., CLSCTX_INPROC_SERVER)` instead of the
     unsupported Windows COM Elevation moniker.
  6. Configures `user.reg` & `system.reg` for Windows 11 (`win11`, Build 22621,
     `Policies\\System` UAC values, ClearType, `Avalon.Graphics`, and native
     VC++ 140 `DllOverrides` to prevent Wine builtin SRWLock deadlocks in OCR).
  7. Synchronizes `HomeFolder` and `ScanSnapHome.db` paths to `SCAN_FOLDER_WIN`,
     defaults double-click/viewer opening to the built-in ScanSnap Home Viewer,
     disables `SsView.exe Optimize` pre-warming via `Configs/SSViewLaunch.ini`,
     and ensures `SsWizard/PfuSsFirmwareUpdate/*_WW.bin` exists.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import struct
import time
import xml.dom.minidom as minidom
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WINEPREFIX = Path(os.environ.get("WINEPREFIX", str(BASE_DIR / "wineprefix")))
SSH_HOME_DIR = WINEPREFIX / "drive_c" / "Program Files (x86)" / "PFU" / "ScanSnap" / "Home"
UPDATE_DIR = WINEPREFIX / "drive_c" / "Program Files (x86)" / "PFU" / "ScanSnap" / "Update"

SERVICEMODEL_REL_PATHS = [
    "drive_c/windows/Microsoft.NET/assembly/GAC_MSIL/System.ServiceModel/v4.0_4.0.0.0__b77a5c561934e089/System.ServiceModel.dll",
    "drive_c/windows/Microsoft.NET/Framework/v4.0.30319/System.ServiceModel.dll",
    "drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/System.ServiceModel.dll",
]

SERVICEMODEL_PATCHES = [
    (
        "NetNamedPipeBinding.CreateTransportSecurity",
        bytes.fromhex("85000c0000000072027b620b00046f5e"),
        bytes.fromhex("85000c0000000072142a620b00046f5e"),
    ),
    (
        "NetNamedPipeSecurity.ctor",
        bytes.fromhex("040228bc00000a02177d640b00042aaa"),
        bytes.fromhex("040228bc00000a02167d640b00042aaa"),
    ),
    (
        "NetNamedPipeSecurity.CreateTransportSecurity",
        bytes.fromhex("037d650b00042a5e027b640b00041733"),
        bytes.fromhex("037d650b00042a5e142a640b00041733"),
    ),
]

UPDATER_OS_PATCHES = [
    (
        "SsUCommon.GetOSVersion_GetVersionExW",
        bytes.fromhex("ffb5f0feffff8d85e4feffffffb5ecfeffff"),
        bytes.fromhex("6a00909090908d85e4feffff6a0a90909090"),
    ),
    (
        "SsUCommon.GetOSVersion_NetWkstaGetInfo",
        bytes.fromhex("56578b780c8b7010"),
        bytes.fromhex("56576a0a5f31f690"),
    ),
]

UPDATER_UAC_ORIG_RE = re.compile(
    rb"\x85\xc0\x75\x1d\x68(.{4})\x68(.{4})\x6a\x04\x50\x68(.{4})\xff\x15",
    re.DOTALL,
)
UPDATER_UAC_PATCHED_RE = re.compile(
    rb"\x31\xc0\x90\x90\x68(.{4})\x68(.{4})\x6a\x01\x50\x68(.{4})\xff\x15",
    re.DOTALL,
)

TERMINATE_WMI_ORIG_RE = re.compile(
    rb"\x1b\x30\x03\x00\xd4\x00\x00\x00(.{4})\x28.{3}\x0a(\x6f.{3}\x0a\x26\x28.{3}\x0a\x6f.{3}\x0a\x0a\x72.{3}\x70\x73)",
    re.DOTALL,
)
TERMINATE_WMI_BROKEN_RE = re.compile(
    rb"\x13\x30\x03\x00\xd4\x00\x00\x00(.{4})\x16\x2a\x00\x00\x00\x00(\x6f.{3}\x0a\x26\x28.{3}\x0a\x6f.{3}\x0a\x0a\x72.{3}\x70\x73)",
    re.DOTALL,
)
TERMINATE_WMI_PATCHED_RE = re.compile(
    rb"\x13\x30\x03\x00\xd4\x00\x00\x00(.{4})\x16\x2a\x00\x00\x00(\x6f.{3}\x0a\x26\x28.{3}\x0a\x6f.{3}\x0a\x0a\x72.{3}\x70\x73)",
    re.DOTALL,
)

MOUTH_CTOR_ORIG_RE = re.compile(
    rb"\x3a\x02\x18(\x7d..\x00\x04\x02\x28..\x00\x0a\x2a)",
    re.DOTALL,
)
MOUTH_CTOR_PATCHED_RE = re.compile(
    rb"\x3a\x02\x17(\x7d..\x00\x04\x02\x28..\x00\x0a\x2a)",
    re.DOTALL,
)


def clear_wine_fonts_dir() -> None:
    """Keep drive_c/windows/Fonts empty so WPF resolves external Fontconfig TTFs."""
    fonts_dir = WINEPREFIX / "drive_c" / "windows" / "Fonts"
    if not fonts_dir.exists():
        fonts_dir.mkdir(parents=True, exist_ok=True)
        return
    removed = 0
    for entry in fonts_dir.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    if removed:
        print(f"[fonts] cleared {removed} files from {fonts_dir}")
    else:
        print(f"[fonts] ok {fonts_dir} (empty)")


def patch_wcf_servicemodel() -> None:
    """Ensure .NET System.ServiceModel.dll NetNamedPipeBinding defaults to Security.None."""
    any_found = False
    any_changed = False
    for rel in SERVICEMODEL_REL_PATHS:
        dll_path = WINEPREFIX / rel
        if not dll_path.exists():
            continue
        any_found = True
        data = bytearray(dll_path.read_bytes())
        changed = False
        for name, orig, patched in SERVICEMODEL_PATCHES:
            if patched in data:
                continue
            idx = data.find(orig)
            if idx == -1:
                raise RuntimeError(f"Pattern for {name} not found in {dll_path}")
            if data.find(orig, idx + 1) != -1:
                raise RuntimeError(f"Ambiguous multiple matches for {name} in {dll_path}")
            data[idx : idx + len(orig)] = patched
            changed = True
            print(f"[wcf-dll] patched {name} in {dll_path}")
        if changed:
            dll_path.write_bytes(bytes(data))
            any_changed = True
        else:
            print(f"[wcf-dll] ok {dll_path}")

    if not any_found:
        print("[wcf-dll] skipped (.NET 4.8 not installed yet)")
        return

    if any_changed:
        asm_dir = WINEPREFIX / "drive_c" / "windows" / "assembly"
        for sub in ("NativeImages_v4.0.30319_32", "NativeImages_v4.0.30319_64"):
            ni_dir = asm_dir / sub
            if ni_dir.exists():
                shutil.rmtree(ni_dir)
                print(f"[wcf-dll] removed stale NGEN cache {ni_dir}")


def patch_wcf_configs() -> None:
    """Ensure all ScanSnap *.config netNamedPipeBinding elements specify security mode=None."""
    if not SSH_HOME_DIR.exists():
        print(f"[wcf-cfg] skipped (ScanSnap Home not installed yet): {SSH_HOME_DIR}")
        return

    patched_files = 0
    checked_files = 0
    for cfg_path in sorted(SSH_HOME_DIR.glob("*.config")):
        raw = cfg_path.read_bytes()
        if b"netNamedPipeBinding" not in raw:
            continue
        checked_files += 1

        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        decl_match = re.match(r"\s*<\?xml[^?]*\?>\r?\n?", text)
        xml_decl = decl_match.group(0) if decl_match else ""

        doc = minidom.parseString(text)
        modified = False
        for pipe_elem in doc.getElementsByTagName("netNamedPipeBinding"):
            has_unnamed = False
            bindings = [
                n for n in pipe_elem.childNodes
                if n.nodeType == n.ELEMENT_NODE and n.tagName == "binding"
            ]
            for binding in bindings:
                if not binding.hasAttribute("name"):
                    has_unnamed = True
                sec_nodes = [
                    n for n in binding.childNodes
                    if n.nodeType == n.ELEMENT_NODE and n.tagName == "security"
                ]
                if not sec_nodes:
                    sec = doc.createElement("security")
                    sec.setAttribute("mode", "None")
                    binding.appendChild(doc.createTextNode("\n          "))
                    binding.appendChild(sec)
                    binding.appendChild(doc.createTextNode("\n        "))
                    modified = True
                else:
                    for sec in sec_nodes:
                        if sec.getAttribute("mode") != "None":
                            sec.setAttribute("mode", "None")
                            modified = True
            if not has_unnamed:
                default_b = doc.createElement("binding")
                sec = doc.createElement("security")
                sec.setAttribute("mode", "None")
                default_b.appendChild(doc.createTextNode("\n          "))
                default_b.appendChild(sec)
                default_b.appendChild(doc.createTextNode("\n        "))
                pipe_elem.appendChild(doc.createTextNode("\n        "))
                pipe_elem.appendChild(default_b)
                pipe_elem.appendChild(doc.createTextNode("\n      "))
                modified = True

        if not modified:
            continue

        body = doc.documentElement.toxml()
        if xml_decl:
            new_text = xml_decl.rstrip("\r\n") + "\n" + body + "\n"
        else:
            new_text = '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"
        if "\r\n" in text:
            new_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
        cfg_path.write_bytes((b"\xef\xbb\xbf" if has_bom else b"") + new_text.encode("utf-8"))
        patched_files += 1
        print(f"[wcf-cfg] patched {cfg_path.name}")

    print(f"[wcf-cfg] summary: {patched_files} patched, {checked_files} checked")


def upsert_reg_section(reg_text: str, section_header: str, entries: dict[str, str]) -> tuple[str, bool]:
    """Idempotently set values inside a Wine .reg section, creating the section if missing."""
    escaped = re.escape(section_header)
    sec_re = re.compile(rf"^(\[{escaped}\][^\n]*\n(?:#time=[^\n]*\n)?)(.*?)(?=\n\[|\Z)", re.MULTILINE | re.DOTALL)
    match = sec_re.search(reg_text)
    now_epoch = int(time.time())
    now_filetime = (now_epoch + 11644473600) * 10_000_000

    if not match:
        lines = [f"[{section_header}] {now_epoch}", f"#time={now_filetime:x}"]
        for k, v in sorted(entries.items()):
            lines.append(f'"{k}"={v}')
        block = "\n".join(lines)
        sep = "\n\n" if not reg_text.endswith("\n\n") else ""
        if reg_text.endswith("\n") and not reg_text.endswith("\n\n"):
            sep = "\n"
        return reg_text + sep + block + "\n", True

    hdr = match.group(1)
    body = match.group(2)
    existing_lines = [ln for ln in body.splitlines() if ln != ""]
    updated_lines = []
    seen_keys = set()
    changed = False

    for ln in existing_lines:
        kv_match = re.match(r'^"([^"]+)"=(.*)$', ln)
        if kv_match and kv_match.group(1) in entries:
            key = kv_match.group(1)
            seen_keys.add(key)
            desired = f'"{key}"={entries[key]}'
            if ln != desired:
                changed = True
            updated_lines.append(desired)
        else:
            updated_lines.append(ln)

    for key, val in sorted(entries.items()):
        if key not in seen_keys:
            updated_lines.append(f'"{key}"={val}')
            changed = True

    if not changed:
        return reg_text, False

    new_body = "\n".join(updated_lines) + "\n"
    new_text = reg_text[: match.start()] + hdr + new_body + reg_text[match.end() :]
    return new_text, True


def update_wine_registry() -> None:
    """Apply ClearType, Avalon.Graphics, and Windows 11 version keys to Wine registry."""
    user_reg = WINEPREFIX / "user.reg"
    if not user_reg.exists():
        print(f"[reg] skipped (missing user.reg): {user_reg}")
        return

    user_txt = user_reg.read_text(encoding="utf-8", errors="surrogateescape")
    user_changed = False
    for section, entries in (
        (
            r"Control Panel\\Desktop",
            {
                "FontSmoothing": '"2"',
                "FontSmoothingType": "dword:00000002",
                "FontSmoothingGamma": "dword:000004b0",
                "FontSmoothingOrientation": "dword:00000001",
            },
        ),
        (
            r"Software\\Microsoft\\Avalon.Graphics",
            {
                "DisableHWAcceleration": "dword:00000001",
                "ClearTypeLevel": "dword:00000064",
                "GammaLevel": "dword:0000076c",
                "PixelStructure": "dword:00000001",
                "TextContrastLevel": "dword:00000001",
            },
        ),
        (
            r"Software\\Wine",
            {
                "Version": '"win11"',
            },
        ),
        (
            r"Software\\Wine\\X11 Driver",
            {
                "GrabFullscreen": '"N"',
            },
        ),
        (
            r"Software\\Wine\\DllOverrides",
            {
                "*concrt140": '"native,builtin"',
                "*msvcp140": '"native,builtin"',
                "*msvcp140_1": '"native,builtin"',
                "*msvcp140_2": '"native,builtin"',
                "*msvcp140_atomic_wait": '"native,builtin"',
                "*msvcp140_codecvt_ids": '"native,builtin"',
                "*vcomp140": '"native,builtin"',
                "*vcruntime140": '"native,builtin"',
                "*vcruntime140_1": '"native,builtin"',
                "*vcruntime140_threads": '"native,builtin"',
            },
        ),
    ):
        user_txt, changed = upsert_reg_section(user_txt, section, entries)
        user_changed |= changed

    if user_changed:
        user_reg.write_text(user_txt, encoding="utf-8", errors="surrogateescape")
        print("[reg] updated user.reg")
    else:
        print("[reg] ok user.reg")

    enforce_win11_registry()


def enforce_win11_registry() -> None:
    """Ensure Windows 11 (NT 10.0 Build 22621) and UAC policy keys are set in Wine system.reg."""
    system_reg = WINEPREFIX / "system.reg"
    if not system_reg.exists():
        print(f"[reg] skipped (missing system.reg): {system_reg}")
        return

    sys_txt = system_reg.read_text(encoding="utf-8", errors="surrogateescape")
    sys_changed = False

    win11_nt_entries = {
        "CSDVersion": '""',
        "CurrentBuild": '"22621"',
        "CurrentBuildNumber": '"22621"',
        "CurrentMajorVersionNumber": "dword:0000000a",
        "CurrentMinorVersionNumber": "dword:00000000",
        "CurrentVersion": '"6.3"',
        "ProductName": '"Microsoft Windows 11"',
    }
    for section, entries in (
        (r"Software\\Microsoft\\Windows NT\\CurrentVersion", win11_nt_entries),
        (r"Software\\Wow6432Node\\Microsoft\\Windows NT\\CurrentVersion", win11_nt_entries),
        (r"System\\ControlSet001\\Control\\Windows", {"CSDVersion": "dword:00000000"}),
        (
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System",
            {
                "EnableLUA": "dword:00000001",
                "ConsentPromptBehaviorAdmin": "dword:00000005",
                "PromptOnSecureDesktop": "dword:00000000",
            },
        ),
    ):
        sys_txt, changed = upsert_reg_section(sys_txt, section, entries)
        sys_changed |= changed

    if sys_changed:
        system_reg.write_text(sys_txt, encoding="utf-8", errors="surrogateescape")
        print("[reg] updated system.reg (win11 Build 22621)")
    else:
        print("[reg] ok system.reg (win11 Build 22621)")


def win_path_to_linux(win_path: str) -> Path | None:
    """Resolve a C:\\... Windows path inside WINEPREFIX to a Linux Path."""
    normalized = win_path.strip().replace("/", "\\")
    if len(normalized) >= 3 and normalized[1:3].lower() == ":\\" and normalized[0].lower() == "c":
        rel_parts = [part for part in normalized[3:].split("\\") if part]
        return WINEPREFIX.joinpath("drive_c", *rel_parts)
    return None


def replace_win_prefix(path_val: str, old_root: str, new_root: str) -> str | None:
    """Replace leading `old_root` prefix (case-insensitive) if matched on segment boundary."""
    if not path_val:
        return None
    old_norm = old_root.rstrip("\\")
    val_norm = path_val.rstrip("\\")
    if val_norm.lower() == old_norm.lower():
        return new_root
    prefix_with_sep = old_norm.lower() + "\\"
    if val_norm.lower().startswith(prefix_with_sep):
        suffix = path_val[len(old_norm) :]
        return new_root + suffix
    return None


def migrate_db_paths(db_path: Path, target_win_path: str, linux_root: Path | None) -> None:
    """Update root Folder.IndexPath and ContentFiles path columns in ScanSnapHome.db."""
    if not db_path.exists():
        return

    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        row = cur.execute(
            "SELECT IndexPath FROM Folder WHERE FolderType = 3 AND ParentFolderId IS NULL LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return
        old_root = str(row[0]).rstrip("\\")
        if old_root.lower() == target_win_path.lower():
            if linux_root is not None:
                for (idx_path,) in cur.execute("SELECT IndexPath FROM Folder").fetchall():
                    if idx_path:
                        sub_linux = win_path_to_linux(str(idx_path))
                        if sub_linux is not None:
                            sub_linux.mkdir(parents=True, exist_ok=True)
            print(f"[folder] db ok ({db_path}): {target_win_path}")
            return

        updated_folders = 0
        for folder_id, idx_path in cur.execute("SELECT FolderId, IndexPath FROM Folder").fetchall():
            if not idx_path:
                continue
            new_idx = replace_win_prefix(str(idx_path), old_root, target_win_path)
            if new_idx is not None:
                cur.execute("UPDATE Folder SET IndexPath = ? WHERE FolderId = ?", (new_idx, folder_id))
                updated_folders += 1
                sub_linux = win_path_to_linux(new_idx)
                if sub_linux is not None:
                    sub_linux.mkdir(parents=True, exist_ok=True)

        cf_cols = cur.execute('PRAGMA table_info("ContentFiles")').fetchall()
        path_cols = [col[1] for col in cf_cols if "path" in col[1].lower()]
        pk_col = cf_cols[0][1] if cf_cols else "ContentFilesId"
        updated_files = 0
        for col_name in path_cols:
            for pk_val, old_val in cur.execute(f'SELECT "{pk_col}", "{col_name}" FROM ContentFiles').fetchall():
                if not old_val:
                    continue
                new_val = replace_win_prefix(str(old_val), old_root, target_win_path)
                if new_val is not None:
                    cur.execute(
                        f'UPDATE ContentFiles SET "{col_name}" = ? WHERE "{pk_col}" = ?',
                        (new_val, pk_val),
                    )
                    updated_files += 1

        con.commit()
        print(f"[folder] migrated {db_path}: {old_root} -> {target_win_path} (folders={updated_folders}, files={updated_files})")
    finally:
        con.close()


def sync_scan_folder(target_win_path: str | None = None) -> None:
    """Sync ScanSnap HomeFolder in user.reg and ScanSnapHome.db to `target_win_path`."""
    target = (target_win_path or os.environ.get("SCAN_FOLDER_WIN") or r"C:\ScanSnapHome").rstrip("\\")
    linux_root = win_path_to_linux(target)
    if linux_root is not None:
        linux_root.mkdir(parents=True, exist_ok=True)

    user_reg = WINEPREFIX / "user.reg"
    if user_reg.exists():
        user_txt = user_reg.read_text(encoding="utf-8", errors="surrogateescape")
        escaped_target = '"' + target.replace("\\", "\\\\") + '"'
        user_txt, reg_changed = upsert_reg_section(
            user_txt,
            r"Software\\PFU\\ScanSnap Home\\Config",
            {"HomeFolder": escaped_target},
        )
        if reg_changed:
            user_reg.write_text(user_txt, encoding="utf-8", errors="surrogateescape")
            print(f"[folder] updated user.reg HomeFolder = {target}")
        else:
            print(f"[folder] ok user.reg HomeFolder = {target}")

    users_dir = WINEPREFIX / "drive_c" / "users"
    if not users_dir.exists():
        return

    seen: set[Path] = set()
    for db_path in sorted(users_dir.glob("*/AppData/Roaming/PFU/ScanSnap Home/Managed/ScanSnapHome.db")):
        resolved = db_path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        migrate_db_paths(db_path, target, linux_root)


def ensure_ww_marker() -> None:
    """Ensure `*_WW.bin` exists in SsWizard/PfuSsFirmwareUpdate for Online Update."""
    if not SSH_HOME_DIR.exists():
        return
    fw_dir = SSH_HOME_DIR / "SsWizard" / "PfuSsFirmwareUpdate"
    if not fw_dir.exists():
        fw_dir.mkdir(parents=True, exist_ok=True)
    if any(fw_dir.glob("*_WW.bin")) or any(fw_dir.glob("*_JP.bin")):
        print(f"[ww] ok {fw_dir}")
        return
    marker = fw_dir / "ScanSnap_WW.bin"
    marker.write_bytes(b"WW\n")
    print(f"[ww] created {marker}")


def patch_updater_os_version() -> None:
    """Ensure ScanSnap Online Update SsUCommon.dll reports Windows 11/10 (10.0) under Wine."""
    dll_path = UPDATE_DIR / "SsUCommon.dll"
    if not dll_path.exists():
        print(f"[updater-dll] skipped (not installed): {dll_path}")
        return

    raw = dll_path.read_bytes()
    data = bytearray(raw)
    changed = False
    for name, orig, patched in UPDATER_OS_PATCHES:
        if patched in data:
            continue
        idx = data.find(orig)
        if idx == -1:
            print(f"[updater-dll] warn: pattern for {name} not found in {dll_path}")
            return
        if data.find(orig, idx + 1) != -1:
            raise RuntimeError(f"Ambiguous multiple matches for {name} in {dll_path}")
        data[idx : idx + len(orig)] = patched
        changed = True
        print(f"[updater-dll] patched {name} in {dll_path}")

    if changed:
        dll_path.write_bytes(bytes(data))
    else:
        print(f"[updater-dll] ok {dll_path}")


def patch_updater_uac() -> None:
    """Load SsUUACBridge via CLSCTX_INPROC_SERVER instead of Elevation COM moniker under Wine."""
    exe_path = UPDATE_DIR / "ScanSnapUpdater.exe"
    if not exe_path.exists():
        print(f"[updater-uac] skipped (not installed): {exe_path}")
        return

    raw = exe_path.read_bytes()
    if UPDATER_UAC_PATCHED_RE.search(raw):
        print(f"[updater-uac] ok {exe_path}")
        return

    matches = list(UPDATER_UAC_ORIG_RE.finditer(raw))
    if not matches:
        print(f"[updater-uac] warn: elevation pattern not found in {exe_path}")
        return
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous multiple elevation matches in {exe_path}")

    match = matches[0]
    replacement = (
        b"\x31\xc0\x90\x90\x68"
        + match.group(1)
        + b"\x68"
        + match.group(2)
        + b"\x6a\x01\x50\x68"
        + match.group(3)
        + b"\xff\x15"
    )
    data = bytearray(raw)
    data[match.start() : match.end()] = replacement
    exe_path.write_bytes(bytes(data))
    print(f"[updater-uac] patched SsUUACBridge elevation in {exe_path}")


def patch_terminate_wmi_deadlock() -> None:
    """Bypass multi-threaded WMI Win32_Process query in SshTerminateHomeProcess.exe that deadlocks Wine wbemprox."""
    exe_path = SSH_HOME_DIR / "SshTerminateHomeProcess.exe"
    if not exe_path.exists():
        print(f"[terminate-wmi] skipped (not installed): {exe_path}")
        return

    raw = exe_path.read_bytes()
    for kind, rx in (
        ("repaired", TERMINATE_WMI_BROKEN_RE),
        ("patched", TERMINATE_WMI_ORIG_RE),
    ):
        matches = list(rx.finditer(raw))
        if not matches:
            continue
        if len(matches) > 1:
            raise RuntimeError(f"Ambiguous multiple WMI matches in {exe_path}")
        match = matches[0]
        replacement = (
            b"\x13\x30\x03\x00\xd4\x00\x00\x00"
            + match.group(1)
            + b"\x16\x2a\x00\x00\x00"
            + match.group(2)
        )
        if kind == "patched" and len(replacement) != (match.end() - match.start()):
            raise RuntimeError("Replacement length mismatch")
        data = bytearray(raw)
        data[match.start() : match.end()] = replacement
        exe_path.write_bytes(bytes(data))
        if kind == "repaired":
            print(f"[terminate-wmi] repaired 5-byte alignment in {exe_path} ({len(data)} bytes)")
        else:
            print(f"[terminate-wmi] patched IsAnyTargetProcessRunByOtherUser in {exe_path}")
        return

    if TERMINATE_WMI_PATCHED_RE.search(raw):
        print(f"[terminate-wmi] ok {exe_path}")
        return

    print(f"[terminate-wmi] warn: WMI pattern not found in {exe_path}")


WINE_I386_DIRS = [
    Path("/usr/lib/x86_64-linux-gnu/wine/i386-windows"),
    Path("/usr/lib/i386-linux-gnu/wine/i386-windows"),
]


def repair_syswow64_dlls() -> None:
    """Replace any 64-bit (0x8664) PE DLLs mistakenly written into 32-bit syswow64 by installers."""
    syswow64 = WINEPREFIX / "drive_c" / "windows" / "syswow64"
    if not syswow64.exists():
        return

    repaired = 0
    for p in sorted(syswow64.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".dll", ".exe"):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if len(raw) <= 0x40 or raw[:2] != b"MZ":
            continue
        pe_off = struct.unpack_from("<I", raw, 0x3C)[0]
        if pe_off + 6 > len(raw) or raw[pe_off : pe_off + 4] != b"PE\x00\x00":
            continue
        machine = struct.unpack_from("<H", raw, pe_off + 4)[0]
        if machine == 0x14C:
            continue

        src_32: Path | None = None
        for d in WINE_I386_DIRS:
            cand = d / p.name.lower()
            if cand.exists():
                src_32 = cand
                break
        if src_32 is None and p.name.lower() == "vcruntime140.dll":
            clr_cand = syswow64 / "vcruntime140_clr0400.dll"
            if clr_cand.exists():
                src_32 = clr_cand

        if src_32 is not None:
            shutil.copyfile(src_32, p)
            repaired += 1
            print(f"[syswow64] replaced 64-bit {p.name} (0x{machine:x}) with 32-bit from {src_32}")
        else:
            p.unlink()
            repaired += 1
            print(f"[syswow64] removed 64-bit {p.name} (0x{machine:x}) from syswow64")

    if repaired == 0:
        print(f"[syswow64] ok {syswow64} (all PE binaries are 32-bit 0x14c)")


def patch_default_viewer_ctor() -> None:
    """Default Mouth.Application in Pfu.ScanSnap.ConfigControl.dll to FILEOPENAPP_VIEWER (1)."""
    dll_path = SSH_HOME_DIR / "Pfu.ScanSnap.ConfigControl.dll"
    if not dll_path.exists():
        print(f"[viewer-dll] skipped (not installed): {dll_path}")
        return

    raw = dll_path.read_bytes()
    if b"FILEOPENAPP_VIEWER" not in raw:
        print(f"[viewer-dll] warn: FILEOPENAPP_VIEWER symbol not found in {dll_path}")
        return

    matches = list(MOUTH_CTOR_ORIG_RE.finditer(raw))
    if len(matches) == 1:
        match = matches[0]
        data = bytearray(raw)
        data[match.start() : match.end()] = b"\x3a\x02\x17" + match.group(1)
        dll_path.write_bytes(bytes(data))
        print(f"[viewer-dll] patched Mouth..ctor default to FILEOPENAPP_VIEWER (1) in {dll_path}")
        return

    if MOUTH_CTOR_PATCHED_RE.search(raw):
        print(f"[viewer-dll] ok {dll_path}")
        return

    print(f"[viewer-dll] warn: Mouth..ctor pattern not matched ({len(matches)} matches) in {dll_path}")


def ensure_viewer_default() -> None:
    """Switch <Mouth Application=\"2\" /> to built-in Viewer (\"1\") in PfuSsHomeOption.config."""
    users_dir = WINEPREFIX / "drive_c" / "users"
    if not users_dir.exists():
        return

    seen: set[Path] = set()
    for cfg_path in sorted(users_dir.glob("*/AppData/Roaming/PFU/ScanSnap Home/Configs/PfuSsHomeOption.config")):
        resolved = cfg_path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        raw = cfg_path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig", errors="replace")
        new_text, count = re.subn(r'(<Mouth\b[^>]*?\bApplication=")2(")', r"\g<1>1\g<2>", text)
        if count > 0 and new_text != text:
            cfg_path.write_bytes((b"\xef\xbb\xbf" if has_bom else b"") + new_text.encode("utf-8"))
            print(f"[viewer-cfg] switched Mouth Application 2 -> 1 in {cfg_path}")
        else:
            print(f"[viewer-cfg] ok {cfg_path}")


def ensure_viewer_no_prewarm() -> None:
    """Disable SsView.exe Optimize pre-warming via Configs/SSViewLaunch.ini (SSView=0)."""
    users_dir = WINEPREFIX / "drive_c" / "users"
    if not users_dir.exists():
        return

    seen: set[Path] = set()
    for user_dir in sorted(users_dir.iterdir()):
        if not user_dir.is_dir() or user_dir.name.lower() == "public":
            continue
        ssh_dir = user_dir / "AppData" / "Roaming" / "PFU" / "ScanSnap Home"
        if not ssh_dir.exists():
            continue
        resolved_ssh = ssh_dir.resolve()
        if resolved_ssh in seen:
            continue
        seen.add(resolved_ssh)

        cfg_dir = ssh_dir / "Configs"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        ini_path = cfg_dir / "SSViewLaunch.ini"

        if not ini_path.exists():
            # Write without UTF-8 BOM so GetPrivateProfileStringW matches [Launch]
            ini_path.write_bytes(b"[Launch]\r\nSSView=0\r\n")
            print(f"[viewer-ini] wrote {ini_path} (SSView=0)")
            continue

        raw = ini_path.read_bytes()
        has_utf8_bom = raw.startswith(b"\xef\xbb\xbf")
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8-sig", errors="replace")

        lines = text.splitlines()
        out_lines: list[str] = []
        in_launch = False
        found_launch = False
        found_key = False
        changed = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_launch and not found_key:
                    out_lines.append("SSView=0")
                    found_key = True
                    changed = True
                in_launch = stripped.lower() == "[launch]"
                if in_launch:
                    found_launch = True
                out_lines.append(line)
                continue

            if in_launch:
                m = re.match(r"^\s*SSView\s*=\s*(.*)$", line, re.IGNORECASE)
                if m:
                    found_key = True
                    if m.group(1).strip() != "0":
                        out_lines.append("SSView=0")
                        changed = True
                    else:
                        out_lines.append(line)
                    continue

            out_lines.append(line)

        if in_launch and not found_key:
            out_lines.append("SSView=0")
            changed = True
        elif not found_launch:
            if out_lines and out_lines[-1].strip():
                out_lines.append("")
            out_lines.extend(["[Launch]", "SSView=0"])
            changed = True

        if changed or has_utf8_bom:
            new_text = "\r\n".join(out_lines) + "\r\n"
            ini_path.write_bytes(new_text.encode("utf-8"))
            print(f"[viewer-ini] updated {ini_path} (SSView=0)")
        else:
            print(f"[viewer-ini] ok {ini_path}")


def main() -> None:
    """Apply and verify all Wine/ScanSnap Home compatibility patches idempotently."""
    parser = argparse.ArgumentParser(description="Patch ScanSnap Home Wine/Docker setup idempotently.")
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Accepted for compatibility; runs all idempotent runtime checks.",
    )
    parser.parse_args()

    clear_wine_fonts_dir()
    repair_syswow64_dlls()
    patch_wcf_servicemodel()
    patch_wcf_configs()
    patch_terminate_wmi_deadlock()
    patch_default_viewer_ctor()
    patch_updater_os_version()
    patch_updater_uac()
    update_wine_registry()
    sync_scan_folder()
    ensure_viewer_default()
    ensure_viewer_no_prewarm()
    ensure_ww_marker()
    print("[done] all ScanSnap Home patches verified/applied cleanly.")


if __name__ == "__main__":
    main()
