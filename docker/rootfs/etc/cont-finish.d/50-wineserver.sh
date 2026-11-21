#!/bin/sh
set -u

WINESERVER=/usr/lib/x86_64-linux-gnu/wine/wineserver
if [ -x "${WINESERVER}" ] && id app >/dev/null 2>&1; then
    su -s /bin/sh app -c "WINEPREFIX=/opt/scansnap/wineprefix ${WINESERVER} -k" || true
fi
