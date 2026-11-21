#!/usr/bin/env python3
"""
X11 self-healing watchdog & Unix-socket HTTP API for ScanSnap Home Web GUI.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_ubyte, c_uint, c_ulong, c_void_p
import http.server
import json
import os
from pathlib import Path
import re
import signal
import socket
import socketserver
import subprocess
import threading
import time

SOCK_PATH = "/tmp/scansnap_wm.sock"
WINEPREFIX = os.environ.get("WINEPREFIX", "/opt/scansnap/wineprefix")
LD_LIBRARY_PATH = os.environ.get("LD_LIBRARY_PATH", "/opt/scansnap/lib64")
LD_PRELOAD = os.environ.get("LD_PRELOAD", "libscansnap_udp.so")

SSH_DIR = r"C:\Program Files (x86)\PFU\ScanSnap\Home"
UPD_EXE = r"C:\Program Files (x86)\PFU\ScanSnap\Update\ScanSnapUpdater.exe"

SERVICES = [
    {"key": "main", "label": "ScanSnap Home", "pattern": r"PfuSshMain\.exe", "exe": f"{SSH_DIR}\\PfuSshMain.exe"},
    {"key": "mon", "label": "Scanner Monitor", "pattern": r"PfuSsMon\.exe", "exe": f"{SSH_DIR}\\PfuSsMon.exe"},
    {"key": "reg", "label": "SshRegister", "pattern": r"SshRegister\.exe", "exe": f"{SSH_DIR}\\SshRegister.exe"},
    {"key": "tray", "label": "Task Tray", "pattern": r"SshTaskTray\.exe", "exe": f"{SSH_DIR}\\SshTaskTray.exe"},
    {"key": "cloud", "label": "Cloud Monitor", "pattern": r"SshCloudMonitor\.exe", "exe": f"{SSH_DIR}\\SshCloudMonitor.exe"},
    {"key": "updater", "label": "Online Update", "pattern": r"ScanSnapUpdater\.exe", "exe": UPD_EXE},
]

IGNORE_TITLES = {
    "",
    "Default IME",
    "Form1",
    "Hidden Window",
    "SsViewMain",
    "ScanSnap Home - []",
    "Viewer - []",
}
IGNORE_TITLE_SUFFIXES = (" - []",)
IGNORE_TITLE_PREFIXES = (
    "PfuSshImg",
    "GlowWindow",
    ".NET-Broadcast",
    "SystemResourceNotifyWindow",
    "MediaContextNotificationWindow",
)
HELPER_CLASSES = {
    "explorer.exe",
    "sshregister.exe",
    "sshtasktray.exe",
    "sshcloudmonitor.exe",
    "pfusshimgproc.exe",
    "pfusshimgmonitor.exe",
}


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int),
        ("border_width", c_int), ("depth", c_int), ("visual", c_void_p),
        ("root", c_ulong), ("c_class", c_int), ("bit_gravity", c_int),
        ("win_gravity", c_int), ("backing_store", c_int),
        ("backing_planes", c_ulong), ("backing_pixel", c_ulong),
        ("save_under", c_int), ("colormap", c_ulong), ("map_installed", c_int),
        ("map_state", c_int), ("all_event_masks", c_long),
        ("your_event_mask", c_long), ("do_not_propagate_mask", c_long),
        ("override_redirect", c_int), ("screen", c_void_p),
    ]


class DataUnion(ctypes.Union):
    _fields_ = [("l", c_long * 5)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", DataUnion),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xclient", XClientMessageEvent),
        ("pad", c_long * 24),
    ]


class XTextProperty(ctypes.Structure):
    _fields_ = [
        ("value", POINTER(c_ubyte)),
        ("encoding", c_ulong),
        ("format", c_int),
        ("nitems", c_ulong),
    ]


class XClassHint(ctypes.Structure):
    _fields_ = [
        ("res_name", c_void_p),
        ("res_class", c_void_p),
    ]


ERROR_HANDLER_TYPE = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
_KEEP_ERROR_HANDLER = ERROR_HANDLER_TYPE(lambda dpy, err: 0)


def detect_display() -> str:
    env_d = os.environ.get("DISPLAY")
    if env_d:
        return env_d
    socks = sorted(Path("/tmp/.X11-unix").glob("X*"))
    for s in socks:
        suffix = s.name[1:]
        if suffix.isdigit():
            return f":{suffix}"
    return ":0"


class X11Controller:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xext = ctypes.CDLL("libXext.so.6")
        self._bind_types()
        self.x11.XSetErrorHandler(_KEEP_ERROR_HANDLER)
        self.dpy: int | None = None
        self.root: int = 0
        self.atoms: dict[str, int] = {}
        self.seen_dialogs: set[int] = set()

    def _bind_types(self) -> None:
        x11, xext = self.x11, self.xext
        x11.XOpenDisplay.argtypes = [c_char_p]
        x11.XOpenDisplay.restype = c_void_p
        x11.XCloseDisplay.argtypes = [c_void_p]
        x11.XDefaultRootWindow.argtypes = [c_void_p]
        x11.XDefaultRootWindow.restype = c_ulong
        x11.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
        x11.XInternAtom.restype = c_ulong
        x11.XQueryTree.argtypes = [
            c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong),
            POINTER(POINTER(c_ulong)), POINTER(c_uint),
        ]
        x11.XQueryTree.restype = c_int
        x11.XGetWindowAttributes.argtypes = [c_void_p, c_ulong, POINTER(XWindowAttributes)]
        x11.XGetWindowAttributes.restype = c_int
        x11.XGetWindowProperty.argtypes = [
            c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
            POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong),
            POINTER(c_ulong), POINTER(POINTER(c_ubyte)),
        ]
        x11.XGetWindowProperty.restype = c_int
        x11.XGetTextProperty.argtypes = [c_void_p, c_ulong, POINTER(XTextProperty), c_ulong]
        x11.XGetTextProperty.restype = c_int
        x11.XGetClassHint.argtypes = [c_void_p, c_ulong, POINTER(XClassHint)]
        x11.XGetClassHint.restype = c_int
        x11.XFree.argtypes = [c_void_p]
        x11.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
        x11.XSendEvent.restype = c_int
        x11.XRaiseWindow.argtypes = [c_void_p, c_ulong]
        x11.XMapWindow.argtypes = [c_void_p, c_ulong]
        x11.XUnmapWindow.argtypes = [c_void_p, c_ulong]
        x11.XSetInputFocus.argtypes = [c_void_p, c_ulong, c_int, c_ulong]
        x11.XFlush.argtypes = [c_void_p]
        x11.XSync.argtypes = [c_void_p, c_int]
        xext.XShapeCombineRectangles.argtypes = [
            c_void_p, c_ulong, c_int, c_int, c_int, c_void_p, c_int, c_int, c_int
        ]

    def ensure_connected(self) -> bool:
        if self.dpy:
            return True
        disp = detect_display().encode("ascii", "ignore")
        dpy = self.x11.XOpenDisplay(disp)
        if not dpy:
            return False
        self.dpy = dpy
        self.root = self.x11.XDefaultRootWindow(dpy)
        for name in (
            "_NET_CLIENT_LIST",
            "_NET_CLIENT_LIST_STACKING",
            "_NET_ACTIVE_WINDOW",
            "_NET_WM_NAME",
            "_NET_WM_STATE",
            "_NET_WM_STATE_BELOW",
            "_NET_WM_STATE_DEMANDS_ATTENTION",
            "_NET_WM_STATE_FULLSCREEN",
            "_NET_WM_STATE_HIDDEN",
            "_NET_WM_WINDOW_TYPE",
            "_NET_WM_WINDOW_TYPE_TOOLTIP",
            "_NET_WM_WINDOW_TYPE_POPUP_MENU",
            "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
            "_NET_WM_WINDOW_TYPE_COMBO",
            "UTF8_STRING",
            "WM_NAME",
        ):
            self.atoms[name] = self.x11.XInternAtom(dpy, name.encode("ascii"), 0)
        return True

    def _get_win_list_prop(self, prop_atom: int) -> list[int]:
        if not self.dpy or not prop_atom:
            return []
        actual_type = c_ulong()
        actual_fmt = c_int()
        nitems = c_ulong()
        bytes_after = c_ulong()
        data = POINTER(c_ubyte)()
        rc = self.x11.XGetWindowProperty(
            self.dpy, self.root, prop_atom, 0, 1024, 0, 0,
            byref(actual_type), byref(actual_fmt), byref(nitems),
            byref(bytes_after), byref(data),
        )
        res: list[int] = []
        if rc == 0 and data:
            if actual_fmt.value == 32 and nitems.value > 0:
                arr = ctypes.cast(data, POINTER(c_ulong))
                res = [int(arr[i]) for i in range(nitems.value)]
            self.x11.XFree(data)
        return res

    def _get_atom_list_prop(self, win: int, prop_atom: int) -> list[int]:
        if not self.dpy or not prop_atom:
            return []
        actual_type = c_ulong()
        actual_fmt = c_int()
        nitems = c_ulong()
        bytes_after = c_ulong()
        data = POINTER(c_ubyte)()
        rc = self.x11.XGetWindowProperty(
            self.dpy, win, prop_atom, 0, 64, 0, 0,
            byref(actual_type), byref(actual_fmt), byref(nitems),
            byref(bytes_after), byref(data),
        )
        res: list[int] = []
        if rc == 0 and data:
            if actual_fmt.value == 32 and nitems.value > 0:
                arr = ctypes.cast(data, POINTER(c_ulong))
                res = [int(arr[i]) for i in range(nitems.value)]
            self.x11.XFree(data)
        return res

    def _get_title(self, win: int) -> str:
        actual_type = c_ulong()
        actual_fmt = c_int()
        nitems = c_ulong()
        bytes_after = c_ulong()
        data = POINTER(c_ubyte)()
        rc = self.x11.XGetWindowProperty(
            self.dpy, win, self.atoms["_NET_WM_NAME"], 0, 512, 0, 0,
            byref(actual_type), byref(actual_fmt), byref(nitems),
            byref(bytes_after), byref(data),
        )
        if rc == 0 and data:
            raw = bytes(data[: nitems.value])
            self.x11.XFree(data)
            if raw:
                return raw.decode("utf-8", "replace").strip("\x00")
        tp = XTextProperty()
        if self.x11.XGetTextProperty(self.dpy, win, byref(tp), self.atoms["WM_NAME"]) and tp.value:
            raw = bytes(tp.value[: tp.nitems])
            self.x11.XFree(tp.value)
            return raw.decode("utf-8", "replace").strip("\x00")
        return ""

    def _get_class(self, win: int) -> str:
        hint = XClassHint()
        if self.x11.XGetClassHint(self.dpy, win, byref(hint)):
            cls = ""
            if hint.res_class:
                cls = ctypes.string_at(hint.res_class).decode("utf-8", "replace")
                self.x11.XFree(hint.res_class)
            if hint.res_name:
                if not cls:
                    cls = ctypes.string_at(hint.res_name).decode("utf-8", "replace")
                self.x11.XFree(hint.res_name)
            return cls.lower()
        return ""

    def _send_wm_state(self, win: int, action: int, atom1: int, atom2: int = 0) -> None:
        ev = XEvent()
        ev.xclient.type = 33
        ev.xclient.display = self.dpy
        ev.xclient.window = win
        ev.xclient.message_type = self.atoms["_NET_WM_STATE"]
        ev.xclient.format = 32
        ev.xclient.data.l[0] = action
        ev.xclient.data.l[1] = atom1
        ev.xclient.data.l[2] = atom2
        ev.xclient.data.l[3] = 2
        ev.xclient.data.l[4] = 0
        self.x11.XSendEvent(self.dpy, self.root, 0, 0x180000, byref(ev))

    def _activate_window(self, win: int) -> None:
        self.x11.XRaiseWindow(self.dpy, win)
        ev = XEvent()
        ev.xclient.type = 33
        ev.xclient.display = self.dpy
        ev.xclient.window = win
        ev.xclient.message_type = self.atoms["_NET_ACTIVE_WINDOW"]
        ev.xclient.format = 32
        ev.xclient.data.l[0] = 2
        ev.xclient.data.l[1] = 0
        ev.xclient.data.l[2] = 0
        self.x11.XSendEvent(self.dpy, self.root, 0, 0x180000, byref(ev))
        self.x11.XSetInputFocus(self.dpy, win, 1, 0)

    def _clear_clip_windows_locked(self) -> int:
        cleared = 0
        r, p, ch, n = c_ulong(), c_ulong(), POINTER(c_ulong)(), c_uint()
        if not self.x11.XQueryTree(self.dpy, self.root, byref(r), byref(p), byref(ch), byref(n)):
            return 0
        try:
            for i in range(n.value):
                w = int(ch[i])
                attr = XWindowAttributes()
                if not self.x11.XGetWindowAttributes(self.dpy, w, byref(attr)):
                    continue
                if attr.map_state == 2 and attr.c_class == 2 and attr.override_redirect == 1:
                    if attr.width >= 400 and attr.height >= 300:
                        self.xext.XShapeCombineRectangles(self.dpy, w, 2, 0, 0, None, 0, 0, 0)
                        self.x11.XUnmapWindow(self.dpy, w)
                        cleared += 1
        finally:
            if ch:
                self.x11.XFree(ch)
        return cleared

    def _collect_windows_locked(self) -> list[dict]:
        active_list = self._get_win_list_prop(self.atoms["_NET_ACTIVE_WINDOW"])
        active_win = active_list[0] if active_list else 0
        client_ids = self._get_win_list_prop(self.atoms["_NET_CLIENT_LIST_STACKING"])
        if not client_ids:
            client_ids = self._get_win_list_prop(self.atoms["_NET_CLIENT_LIST"])

        below_atom = self.atoms["_NET_WM_STATE_BELOW"]
        demands_attn_atom = self.atoms["_NET_WM_STATE_DEMANDS_ATTENTION"]
        fs_atom = self.atoms["_NET_WM_STATE_FULLSCREEN"]
        hidden_atom = self.atoms["_NET_WM_STATE_HIDDEN"]
        win_type_atom = self.atoms["_NET_WM_WINDOW_TYPE"]
        skip_types = {
            self.atoms[k]
            for k in (
                "_NET_WM_WINDOW_TYPE_TOOLTIP",
                "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
                "_NET_WM_WINDOW_TYPE_COMBO",
            )
            if self.atoms.get(k)
        }

        raw_windows = []
        for w in client_ids:
            attr = XWindowAttributes()
            if not self.x11.XGetWindowAttributes(self.dpy, w, byref(attr)):
                continue
            win_types = self._get_atom_list_prop(w, win_type_atom)
            if any(t in skip_types for t in win_types):
                continue
            states = self._get_atom_list_prop(w, self.atoms["_NET_WM_STATE"])
            minimized = (attr.map_state != 2) or (hidden_atom in states)
            title = self._get_title(w)
            if (
                title in IGNORE_TITLES
                or any(title.startswith(pfx) for pfx in IGNORE_TITLE_PREFIXES)
                or any(title.endswith(sfx) for sfx in IGNORE_TITLE_SUFFIXES)
            ):
                continue
            wm_class = self._get_class(w)
            if wm_class in HELPER_CLASSES and (minimized or attr.width <= 260):
                continue
            # Wine gives minimized real application windows 160x31 geometry; only filter tiny non-minimized helper windows
            if not minimized and (attr.width <= 180 or attr.height <= 40):
                continue
            raw_windows.append({
                "win": w,
                "id": hex(w),
                "title": title or wm_class or hex(w),
                "wm_class": wm_class,
                "width": attr.width,
                "height": attr.height,
                "minimized": minimized,
                "below": below_atom in states,
                "demands_attention": demands_attn_atom in states,
                "fullscreen": fs_atom in states,
                "active": w == active_win,
            })

        # Identify the primary ScanSnap Home window (largest pfusshmain.exe window)
        main_win_id = 0
        best_area = 0
        for item in raw_windows:
            if item["wm_class"] == "pfusshmain.exe" and item["title"] == "ScanSnap Home":
                area = item["width"] * item["height"]
                if item["width"] >= 800 and item["height"] >= 500 and area > best_area:
                    best_area = area
                    main_win_id = item["win"]

        for item in raw_windows:
            item["is_main"] = item["win"] == main_win_id
            item["is_dialog"] = not item["is_main"]

        return raw_windows

    def heal_once(self) -> None:
        with self.lock:
            if not self.ensure_connected():
                return
            self._clear_clip_windows_locked()
            wins = self._collect_windows_locked()
            below_atom = self.atoms["_NET_WM_STATE_BELOW"]
            demands_attn_atom = self.atoms["_NET_WM_STATE_DEMANDS_ATTENTION"]
            main_wins = [w for w in wins if w["is_main"]]

            changed = False
            dialogs = [w for w in wins if w["is_dialog"] and not w["minimized"]]
            self.seen_dialogs.intersection_update({w["win"] for w in dialogs})

            for d in dialogs:
                if d["below"]:
                    self._send_wm_state(d["win"], 0, below_atom)
                    if d["active"]:
                        self._activate_window(d["win"])
                    changed = True

            # Auto-raise newly launched or attention-requesting child/viewer windows (e.g. SsView.exe)
            # once so Openbox focus-stealing prevention never traps them behind pfusshmain.exe.
            new_dialogs = [w for w in dialogs if w["win"] not in self.seen_dialogs]
            attn_dialogs = [w for w in dialogs if w["demands_attention"] and w["win"] in self.seen_dialogs]
            self.seen_dialogs.update(w["win"] for w in dialogs)
            to_raise = new_dialogs + attn_dialogs
            if to_raise:
                raise_classes = {w["wm_class"] for w in to_raise if w["wm_class"]}
                raise_map = {w["win"]: w for w in to_raise}
                for d in dialogs:
                    if d["wm_class"] in raise_classes:
                        raise_map[d["win"]] = d
                raise_batch = sorted(raise_map.values(), key=lambda w: w["width"] * w["height"], reverse=True)
                for w in raise_batch:
                    if w["below"]:
                        self._send_wm_state(w["win"], 0, below_atom)
                    if w["demands_attention"]:
                        self._send_wm_state(w["win"], 0, demands_attn_atom)
                    self.x11.XRaiseWindow(self.dpy, w["win"])
                self._activate_window(raise_batch[-1]["win"])
                changed = True

            # Only force main window below if it is stuck in fullscreen while a dialog exists
            if dialogs:
                smallest = min(dialogs, key=lambda w: w["width"] * w["height"])
                for mw in main_wins:
                    if mw["fullscreen"] and not mw["below"]:
                        self._send_wm_state(mw["win"], 1, below_atom)
                        self._activate_window(smallest["win"])
                        changed = True

            if changed:
                self.x11.XFlush(self.dpy)
                self.x11.XSync(self.dpy, 0)

    def get_windows(self) -> list[dict]:
        with self.lock:
            if not self.ensure_connected():
                return []
            wins = self._collect_windows_locked()
            return [
                {
                    "id": w["id"],
                    "title": w["title"],
                    "wm_class": w["wm_class"],
                    "width": w["width"],
                    "height": w["height"],
                    "active": w["active"],
                    "minimized": w["minimized"],
                    "is_dialog": w["is_dialog"],
                }
                for w in wins
            ]

    def focus_window(self, win_id_str: str) -> bool:
        try:
            target = int(win_id_str, 16) if win_id_str.startswith("0x") else int(win_id_str)
        except ValueError:
            return False

        with self.lock:
            if not self.ensure_connected():
                return False
            self._clear_clip_windows_locked()
            wins = self._collect_windows_locked()
            by_id = {w["win"]: w for w in wins}
            if target not in by_id:
                return False

            below_atom = self.atoms["_NET_WM_STATE_BELOW"]
            hidden_atom = self.atoms["_NET_WM_STATE_HIDDEN"]
            item = by_id[target]

            if item["minimized"]:
                self._send_wm_state(target, 0, hidden_atom)
                self.x11.XMapWindow(self.dpy, target)

            if item["below"]:
                self._send_wm_state(target, 0, below_atom)

            if item["is_dialog"]:
                for w in wins:
                    if w["is_main"] and w["fullscreen"] and not w["below"]:
                        self._send_wm_state(w["win"], 1, below_atom)

            self._activate_window(target)
            self.x11.XFlush(self.dpy)
            self.x11.XSync(self.dpy, 0)
            return True

    def raise_dialogs(self) -> int:
        with self.lock:
            if not self.ensure_connected():
                return 0
            self._clear_clip_windows_locked()
            wins = self._collect_windows_locked()
            below_atom = self.atoms["_NET_WM_STATE_BELOW"]
            hidden_atom = self.atoms["_NET_WM_STATE_HIDDEN"]
            dialogs = [w for w in wins if w["is_dialog"]]
            if dialogs:
                dialogs.sort(key=lambda w: w["width"] * w["height"], reverse=True)
                for mw in wins:
                    if mw["is_main"] and mw["fullscreen"] and not mw["below"]:
                        self._send_wm_state(mw["win"], 1, below_atom)
                for d in dialogs:
                    if d["minimized"]:
                        self._send_wm_state(d["win"], 0, hidden_atom)
                        self.x11.XMapWindow(self.dpy, d["win"])
                    if d["below"]:
                        self._send_wm_state(d["win"], 0, below_atom)
                    self.x11.XRaiseWindow(self.dpy, d["win"])
                self._activate_window(dialogs[-1]["win"])
            else:
                for mw in wins:
                    if mw["below"]:
                        self._send_wm_state(mw["win"], 0, below_atom)
                    if mw["minimized"]:
                        self._send_wm_state(mw["win"], 0, hidden_atom)
                        self.x11.XMapWindow(self.dpy, mw["win"])
                    self._activate_window(mw["win"])
            self.x11.XFlush(self.dpy)
            self.x11.XSync(self.dpy, 0)
            return len(dialogs)


def find_service_pids(pattern: str) -> list[int]:
    rx = re.compile(pattern, re.IGNORECASE)
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        cmd = raw.replace(b"\x00", b" ").decode("utf-8", "ignore")
        if rx.search(cmd):
            pids.append(int(entry.name))
    return sorted(pids)


def get_services_status() -> list[dict]:
    out = []
    for svc in SERVICES:
        pids = find_service_pids(svc["pattern"])
        out.append({
            "key": svc["key"],
            "label": svc["label"],
            "running": len(pids) > 0,
            "pids": pids,
        })
    return out


def control_service(target: str, op: str) -> tuple[bool, str]:
    svc = next((s for s in SERVICES if s["key"] == target), None)
    if not svc or op not in ("start", "stop", "restart"):
        return False, "invalid target or op"

    pause_file = Path(f"/tmp/scansnap_{target}_paused")

    if op in ("stop", "restart"):
        pause_file.touch()
        for pid in find_service_pids(svc["pattern"]):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(10):
            if not find_service_pids(svc["pattern"]):
                break
            time.sleep(0.2)
        remaining = find_service_pids(svc["pattern"])
        if remaining:
            for pid in remaining:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            for _ in range(5):
                if not find_service_pids(svc["pattern"]):
                    break
                time.sleep(0.2)
        if op == "stop":
            return True, "stopped"

    if op in ("start", "restart"):
        if op == "start" and find_service_pids(svc["pattern"]):
            pause_file.unlink(missing_ok=True)
            return True, "already running"
        pause_file.unlink(missing_ok=True)
        if target == "main":
            for _ in range(13):
                if find_service_pids(svc["pattern"]):
                    return True, "started"
                time.sleep(0.2)
        env = os.environ.copy()
        env["LANG"] = env.get("LANG") or "en_US.UTF-8"
        env["LC_ALL"] = env.get("LC_ALL") or env["LANG"]
        env["DISPLAY"] = detect_display()
        env["WINEPREFIX"] = WINEPREFIX
        env["PATH"] = f"/opt/scansnap/bin:{env.get('PATH', '')}"
        env["LD_LIBRARY_PATH"] = LD_LIBRARY_PATH
        env["LD_PRELOAD"] = LD_PRELOAD
        log_path = f"/tmp/scansnap_svc_{svc['key']}.log"
        with open(log_path, "ab") as log_f:
            subprocess.Popen(
                ["wine", svc["exe"]],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        return True, "started"

    return False, "unhandled"


X11 = X11Controller()


class RequestHandler(http.server.BaseHTTPRequestHandler):
    def address_string(self) -> str:
        return "unix"

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/status", "/scansnap-api/status"):
            self._send_json(200, {
                "windows": X11.get_windows(),
                "services": get_services_status(),
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/action", "/scansnap-api/action"):
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            req = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return

        action = req.get("action")
        if action == "focus_window":
            ok = X11.focus_window(str(req.get("id", "")))
            self._send_json(200, {"ok": ok})
        elif action == "raise_dialogs":
            cnt = X11.raise_dialogs()
            self._send_json(200, {"ok": True, "dialogs": cnt})
        elif action == "service":
            ok, msg = control_service(str(req.get("target", "")), str(req.get("op", "")))
            self._send_json(200, {"ok": ok, "message": msg})
        else:
            self._send_json(400, {"ok": False, "error": "unknown action"})


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def watchdog_loop() -> None:
    while True:
        try:
            X11.heal_once()
        except Exception:
            pass
        time.sleep(0.4)


def main() -> None:
    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)
    threading.Thread(target=watchdog_loop, daemon=True).start()
    server = UnixHTTPServer(SOCK_PATH, RequestHandler)
    os.chmod(SOCK_PATH, 0o666)
    print(f"[scansnap-wm] listening on {SOCK_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
