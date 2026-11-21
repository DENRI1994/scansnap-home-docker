#!/usr/bin/env bash
set -euo pipefail

RC_XML="/var/run/openbox/rc.xml"
if [ -f "${RC_XML}" ]; then
python3 - <<'PY'
import re
from pathlib import Path

rc_path = Path("/var/run/openbox/rc.xml")
orig_txt = rc_path.read_text(encoding="utf-8")

# Reserve a 1px bottom margin so borderless maximized Wine windows never match
# exact screen size and trigger winex11 fullscreen + clip_window mouse grabs.
new_txt = re.sub(
    r"<margins>.*?</margins>",
    lambda m: m.group(0).replace("<bottom>0</bottom>", "<bottom>1</bottom>"),
    orig_txt,
    flags=re.DOTALL,
)

# Keep main window and modal "ScanSnap Home" dialogs on normal layer without fullscreen
# so dialogs are never trapped beneath Preferences ("Voreinstellungen").
def _fix_pfu_app(match):
    block = match.group(0).replace("<layer>below</layer>", "<layer>normal</layer>")
    if "<fullscreen>" not in block:
        block = block.replace("</application>", "    <fullscreen>no</fullscreen>\n  </application>")
    return block

new_txt = re.sub(
    r"<application[^>]*pfusshmain\.exe[^>]*>.*?</application>",
    _fix_pfu_app,
    new_txt,
    flags=re.DOTALL,
)

marker = "<!-- scansnap-wine-rules -->"
if marker not in new_txt:
    wine_rules = """  <!-- scansnap-wine-rules -->
  <!-- Keep invisible/tray Wine helper windows minimized and out of taskbar/desktop -->
  <application class="explorer.exe">
    <decor>no</decor>
    <iconic>yes</iconic>
    <skip_taskbar>yes</skip_taskbar>
    <skip_pager>yes</skip_pager>
  </application>
  <application class="sshregister.exe">
    <decor>no</decor>
    <iconic>yes</iconic>
    <skip_taskbar>yes</skip_taskbar>
    <skip_pager>yes</skip_pager>
  </application>
  <application class="sshtasktray.exe">
    <decor>no</decor>
    <iconic>yes</iconic>
    <skip_taskbar>yes</skip_taskbar>
    <skip_pager>yes</skip_pager>
  </application>

</applications>"""
    if "</applications>" not in new_txt:
        raise RuntimeError(f"Expected </applications> in {rc_path}")
    new_txt = new_txt.replace("</applications>", wine_rules, 1)

if new_txt != orig_txt:
    rc_path.write_text(new_txt, encoding="utf-8")
PY
fi

# Configure NGINX reverse proxy for /scansnap-api/ -> Unix socket
AUTH_CONF="/var/tmp/nginx/auth.conf"
if [ -f "${AUTH_CONF}" ] && ! grep -q "scansnap-api" "${AUTH_CONF}"; then
  cat <<'NGX' >> "${AUTH_CONF}"

location /scansnap-api/ {
	proxy_pass http://unix:/tmp/scansnap_wm.sock:/;
	proxy_http_version 1.1;
	add_header Cache-Control no-cache;
}
NGX
fi

# Inject ScanSnap sidebar extension into noVNC index.html
INDEX_HTML="/opt/noVNC/index.html"
if [ -f "${INDEX_HTML}" ] && ! grep -q "scansnap-sidebar.js" "${INDEX_HTML}"; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/opt/noVNC/index.html")
txt = p.read_text(encoding="utf-8")
tag = '    <script src="app/scansnap-sidebar.js?v=UNIQUE_VERSION" defer></script>\n</body>'
if "</body>" in txt and "scansnap-sidebar.js" not in txt:
    p.write_text(txt.replace("</body>", tag, 1), encoding="utf-8")
PY
fi

# Start X11 self-healing watchdog + Unix socket API daemon as user app (detached)
if [ -f /opt/scansnap/scansnap_wm_daemon.py ] && ! pgrep -f "scansnap_wm_daemon\.py" >/dev/null 2>&1; then
  rm -f /tmp/scansnap_wm.sock
  setsid su -s /bin/sh app -c "LANG=${LANG:-en_US.UTF-8} LC_ALL=${LC_ALL:-${LANG:-en_US.UTF-8}} WINEPREFIX=/opt/scansnap/wineprefix HOME=/config exec python3 /opt/scansnap/scansnap_wm_daemon.py >/tmp/scansnap_wm.log 2>&1 </dev/null" >/dev/null 2>&1 </dev/null &
fi
