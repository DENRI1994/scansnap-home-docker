#!/usr/bin/env bash
set -euo pipefail

WINEPREFIX=/opt/scansnap/wineprefix
SCAN_FOLDER_WIN="${SCAN_FOLDER_WIN:-C:\\ScanSnapHome}"
UID_VAL="${USER_ID:-1000}"
GID_VAL="${GROUP_ID:-1000}"

SCAN_DIR="${WINEPREFIX}/drive_c/ScanSnapHome"
USERS_DIR="${WINEPREFIX}/drive_c/users"
SSH_EXE="${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/PfuSshMain.exe"

mkdir -p "${WINEPREFIX}" \
         "${SCAN_DIR}" \
         /installer \
         /config/Desktop \
         /config/Downloads \
         /config/Music \
         /config/Pictures \
         /config/Videos

chown "${UID_VAL}:${GID_VAL}" \
      /config/Desktop \
      /config/Downloads \
      /config/Music \
      /config/Pictures \
      /config/Videos

# Align Wine prefix ownership when fresh volume, root-owned, or UID/GID differs (do not recurse into host SCANS_DIR)
cur_owner="$(stat -c '%u:%g' "${WINEPREFIX}/user.reg" 2>/dev/null || echo '')"
if [ "${cur_owner}" != "${UID_VAL}:${GID_VAL}" ]; then
  find "${WINEPREFIX}" -path "${SCAN_DIR}" -prune -o -exec chown -h "${UID_VAL}:${GID_VAL}" {} + 2>/dev/null || true
  chown -h "${UID_VAL}:${GID_VAL}" "${SCAN_DIR}" 2>/dev/null || true
fi

# Support migrated prefixes whose Windows profile directory is named differently from `app`
ACTIVE_USER_DIR="${USERS_DIR}/app"
LEGACY_USER_DIR="$(find "${USERS_DIR}" -mindepth 1 -maxdepth 1 -type d ! -name 'Public' ! -name 'app' 2>/dev/null | head -n 1 || true)"
if [ -n "${LEGACY_USER_DIR}" ]; then
  ACTIVE_USER_DIR="${LEGACY_USER_DIR}"
  if [ ! -L "${USERS_DIR}/app" ]; then
    if [ -d "${USERS_DIR}/app" ]; then
      cp -an "${USERS_DIR}/app/." "${LEGACY_USER_DIR}/" 2>/dev/null || true
      rm -rf "${USERS_DIR}/app"
    fi
    ln -sfn "$(basename "${LEGACY_USER_DIR}")" "${USERS_DIR}/app"
  fi
  chown -h "${UID_VAL}:${GID_VAL}" "${USERS_DIR}/app"
fi

APPDATA_SSH="${ACTIVE_USER_DIR}/AppData/Roaming/PFU/ScanSnap Home"
mkdir -p "${APPDATA_SSH}"
chown "${UID_VAL}:${GID_VAL}" \
      "${USERS_DIR}" \
      "${ACTIVE_USER_DIR}" \
      "${ACTIVE_USER_DIR}/AppData" \
      "${ACTIVE_USER_DIR}/AppData/Roaming" \
      "${ACTIVE_USER_DIR}/AppData/Roaming/PFU" \
      "${APPDATA_SSH}" 2>/dev/null || true

link_to_scan_dir() {
  local target="$1"
  if [ -L "$target" ]; then
    ln -sfn "${SCAN_DIR}" "$target"
  elif [ -d "$target" ]; then
    cp -an "${target}/." "${SCAN_DIR}/" 2>/dev/null || true
    rm -rf "$target"
    ln -sfn "${SCAN_DIR}" "$target"
  else
    ln -sfn "${SCAN_DIR}" "$target"
  fi
  chown -h "${UID_VAL}:${GID_VAL}" "$target"
}

link_to_scan_dir /config/scans
link_to_scan_dir /config/Documents
link_to_scan_dir "${ACTIVE_USER_DIR}/Documents"
link_to_scan_dir "${APPDATA_SSH}/ScanSnap Home"

# If already installed, enforce runtime patches now before starting X11/Wine services;
# on a fresh volume, firstboot_install.sh runs interactively inside startapp.sh.
if [ -f "${SSH_EXE}" ]; then
  export WINEPREFIX SCAN_FOLDER_WIN
  python3 /opt/scansnap/patch_scansnap.py --runtime

  chown -h "${UID_VAL}:${GID_VAL}" \
    "${WINEPREFIX}/user.reg" \
    "${WINEPREFIX}/system.reg" \
    "${SCAN_DIR}" \
    "${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/SsWizard/PfuSsFirmwareUpdate" \
    "${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/SsWizard/PfuSsFirmwareUpdate/ScanSnap_WW.bin" \
    "${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Update/SsUCommon.dll" \
    "${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Update/ScanSnapUpdater.exe" \
    "${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/"*.config 2>/dev/null || true
fi
