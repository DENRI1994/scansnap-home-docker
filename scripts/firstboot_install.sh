#!/usr/bin/env bash
set -euo pipefail

WINEPREFIX="${WINEPREFIX:-/opt/scansnap/wineprefix}"
WINESERVER="/usr/lib/x86_64-linux-gnu/wine/wineserver"
SSH_EXE="${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/PfuSshMain.exe"
INSTALLER_MOUNT="${INSTALLER_MOUNT:-/installer}"
SCAN_FOLDER_WIN="${SCAN_FOLDER_WIN:-C:\\ScanSnapHome}"
SCAN_DIR="${WINEPREFIX}/drive_c/ScanSnapHome"
OCR_LANGS="${OCR_LANGS:-1,6}"

WORK_DIR="/tmp/scansnap_setup"
STATUS_PID=""

cleanup() {
  if [ -n "${STATUS_PID}" ] && kill -0 "${STATUS_PID}" 2>/dev/null; then
    kill "${STATUS_PID}" 2>/dev/null || true
    wait "${STATUS_PID}" 2>/dev/null || true
  fi
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT INT TERM

show_status() {
  local msg
  msg="$(printf '%b' "$1")"
  echo "[firstboot] $(echo "${msg}" | tr '\n' ' ')"
  if [ -n "${STATUS_PID}" ] && kill -0 "${STATUS_PID}" 2>/dev/null; then
    kill "${STATUS_PID}" 2>/dev/null || true
    wait "${STATUS_PID}" 2>/dev/null || true
  fi
  if [ -n "${DISPLAY:-}" ] && command -v xmessage >/dev/null 2>&1; then
    xmessage -center -buttons "" -title "ScanSnap Home Setup" "${msg}" >/dev/null 2>&1 &
    STATUS_PID=$!
  fi
}

find_installer() {
  find "${INSTALLER_MOUNT}" -maxdepth 2 -type f \( -iname 'WinSSH*.exe' -o -iname 'WinSSHome*.exe' \) 2>/dev/null | sort | head -n 1 || true
}

wait_for_stable_file() {
  local f="$1"
  local s1 s2
  while true; do
    s1="$(stat -c '%s' "$f" 2>/dev/null || echo 0)"
    sleep 3
    s2="$(stat -c '%s' "$f" 2>/dev/null || echo 0)"
    if [ "$s1" -gt 0 ] && [ "$s1" = "$s2" ]; then
      break
    fi
  done
}

run_iss_installer() {
  local exe_path="$1"
  local iss_path="$2"
  local log_path="$3"
  local win_iss win_log rc_line waited=0
  win_iss="$(winepath -w "${iss_path}")"
  win_log="$(winepath -w "${log_path}")"
  echo "[firstboot] Running $(basename "${exe_path}") with $(basename "${iss_path}")..."
  WINEDEBUG=-all wine "${exe_path}" /s "/f1${win_iss}" "/f2${win_log}" || true
  while pgrep -fi 'ISBEW64|IDriver|msiexec|ISSetup' >/dev/null 2>&1 && [ "${waited}" -lt 300 ]; do
    sleep 2
    waited=$((waited + 2))
  done
  if [ -f "${log_path}" ]; then
    rc_line="$(tr -d '\0\r' < "${log_path}" | grep -i 'ResultCode=' | tail -n 1 || true)"
    [ -n "${rc_line}" ] && echo "[firstboot] $(basename "${exe_path}") -> ${rc_line}"
  fi
  # Stop resident Windows services (e.g. SsWiaRestartSvc.exe) and wait for registry flush
  "${WINESERVER}" -k || true
  "${WINESERVER}" -w || true
}

# Do NOT inject LD_PRELOAD during .NET 4.8 / InstallShield setup
unset LD_PRELOAD || true
export WINEPREFIX WINESERVER WINEARCH=win64 WINEDEBUG=-all

mkdir -p "${WORK_DIR}" "${WINEPREFIX}" "${SCAN_DIR}"

INSTALLER_EXE="$(find_installer)"
if [ -z "${INSTALLER_EXE}" ] && [ -n "${SCANSNAP_INSTALLER_URL:-}" ]; then
  show_status "Downloading official ScanSnap Home installer...\n\nSource: ${SCANSNAP_INSTALLER_URL}"
  curl -fSL --retry 3 -o "${WORK_DIR}/WinSSHOfflineInstaller.exe" "${SCANSNAP_INSTALLER_URL}"
  INSTALLER_EXE="${WORK_DIR}/WinSSHOfflineInstaller.exe"
fi

if [ -z "${INSTALLER_EXE}" ]; then
  show_status "ScanSnap Home is not installed yet.\n\nPlease download the official Windows Offline Installer\n(WinSSHOfflineInstaller_*.exe) from Ricoh / PFU\nand place it into ./installer/ on the host.\n\nSetup will start automatically once the file is ready."
  while [ -z "${INSTALLER_EXE}" ]; do
    sleep 5
    INSTALLER_EXE="$(find_installer)"
  done
fi

wait_for_stable_file "${INSTALLER_EXE}"

# 1/5 Initialize clean Wine prefix
show_status "Step 1/5: Initializing Windows environment...\n\nInstaller: $(basename "${INSTALLER_EXE}")"
wineboot -u || true
"${WINESERVER}" -w || true
python3 /opt/scansnap/patch_scansnap.py --runtime || true

# 2/5 Install .NET Framework 4.8
show_status "Step 2/5: Installing Microsoft .NET Framework 4.8...\n\nThis takes about 2-5 minutes and runs automatically."
winetricks -q --force dotnet48
"${WINESERVER}" -w || true
rm -rf "${HOME}/.cache/winetricks" \
       "${WINEPREFIX}/drive_c/windows/assembly/NativeImages_v4.0.30319_32" \
       "${WINEPREFIX}/drive_c/windows/assembly/NativeImages_v4.0.30319_64"
python3 /opt/scansnap/patch_scansnap.py --runtime

# 3/5 Unpack ScanSnap Offline Installer bundle (supports nested wrapper layers)
show_status "Step 3/5: Unpacking ScanSnap Home installer bundle...\n\n$(basename "${INSTALLER_EXE}")"
DL_DIR=""
CUR_EXE="${INSTALLER_EXE}"
for depth in 1 2 3; do
  STEP_IS="${WORK_DIR}/is_${depth}"
  STEP_CAB="${WORK_DIR}/cab_${depth}"
  mkdir -p "${STEP_IS}" "${STEP_CAB}"
  echo "[firstboot] Unpacking layer ${depth}: $(basename "${CUR_EXE}")"
  if ! python3 /opt/scansnap/unpack_is.py "${CUR_EXE}" "${STEP_IS}"; then
    rm -rf "${STEP_IS}" "${STEP_CAB}"
    break
  fi
  if [ "${depth}" -gt 1 ]; then
    rm -rf "${WORK_DIR}/cab_$((depth - 1))"
  fi
  CAB_FILE="$(find "${STEP_IS}" -maxdepth 1 -iname 'data1.cab' | head -n 1 || true)"
  if [ -z "${CAB_FILE}" ] || ! unshield -d "${STEP_CAB}" x "${CAB_FILE}" >/dev/null 2>&1; then
    rm -rf "${STEP_IS}" "${STEP_CAB}"
    break
  fi
  rm -rf "${STEP_IS}"
  FOUND_HOME="$(find "${STEP_CAB}" -type f -iname 'WinSSHomeInstaller_*.exe' | head -n 1 || true)"
  if [ -n "${FOUND_HOME}" ]; then
    DL_DIR="$(dirname "${FOUND_HOME}")"
    echo "[firstboot] Found payload directory at layer ${depth}: ${DL_DIR}"
    break
  fi
  NEXT_EXE="$(find "${STEP_CAB}" -type f \( -iname 'WinSSHDownloadInstaller*.exe' -o -iname 'WinSSHOfflineInstaller*.exe' \) | head -n 1 || true)"
  if [ -z "${NEXT_EXE}" ]; then
    echo "[firstboot] No nested installer found at layer ${depth}"
    break
  fi
  CUR_EXE="${NEXT_EXE}"
done

# 4/5 Install ScanSnap Home + AI + requested OCR Packs + Online Update
if [ -n "${DL_DIR}" ] && compgen -G "${DL_DIR}/WinSSHomeInstaller_*.exe" >/dev/null; then
  HOME_INST="$(ls "${DL_DIR}"/WinSSHomeInstaller_*.exe | head -n 1)"
  HOME_ISS="${HOME_INST%.exe}.iss"
  show_status "Step 4/5: Installing ScanSnap Home...\n\nPlease wait (about 2-4 minutes)."
  run_iss_installer "${HOME_INST}" "${HOME_ISS}" "${WORK_DIR}/home_install.log"

  if compgen -G "${DL_DIR}/WinScanSnapAI_*.exe" >/dev/null; then
    AI_INST="$(ls "${DL_DIR}"/WinScanSnapAI_*.exe | head -n 1)"
    AI_ISS="${AI_INST%.exe}.iss"
    show_status "Step 4/5: Installing ScanSnap AI component..."
    run_iss_installer "${AI_INST}" "${AI_ISS}" "${WORK_DIR}/ai_install.log"
  fi

  case "${OCR_LANGS,,}" in
    none|"")
      echo "[firstboot] OCR_LANGS=none, skipping OCR packs"
      ;;
    all)
      for ocr_exe in "${DL_DIR}"/WinScanSnapHOCRPackage*.exe; do
        [ -f "${ocr_exe}" ] || continue
        show_status "Step 4/5: Installing OCR pack ($(basename "${ocr_exe}"))..."
        run_iss_installer "${ocr_exe}" "${ocr_exe%.exe}.iss" "${WORK_DIR}/$(basename "${ocr_exe%.exe}").log"
      done
      ;;
    *)
      IFS=',' read -ra LANG_IDS <<< "${OCR_LANGS}"
      for raw_id in "${LANG_IDS[@]}"; do
        clean_id="$(echo "${raw_id}" | tr -dc '0-9')"
        [ -n "${clean_id}" ] || continue
        padded_id="$(printf '%03d' "$((10#${clean_id}))")"
        if compgen -G "${DL_DIR}/WinScanSnapHOCRPackage${padded_id}_*.exe" >/dev/null; then
          ocr_exe="$(ls "${DL_DIR}"/WinScanSnapHOCRPackage${padded_id}_*.exe | head -n 1)"
          show_status "Step 4/5: Installing OCR pack ${padded_id}..."
          run_iss_installer "${ocr_exe}" "${ocr_exe%.exe}.iss" "${WORK_DIR}/ocr_${padded_id}.log"
        else
          echo "[firstboot] warn: OCR pack ${padded_id} not found in installer bundle"
        fi
      done
      ;;
  esac

  if compgen -G "${DL_DIR}/WinOnlineUpdate*.exe" >/dev/null; then
    UPD_INST="$(ls "${DL_DIR}"/WinOnlineUpdate*.exe | head -n 1)"
    UPD_ISS="$(ls "${DL_DIR}"/WinOnlineUpdate*.iss | grep -v '_ug\.iss$' | head -n 1 || true)"
    if [ -n "${UPD_ISS}" ]; then
      show_status "Step 4/5: Installing ScanSnap Online Update..."
      run_iss_installer "${UPD_INST}" "${UPD_ISS}" "${WORK_DIR}/online_update.log"
    fi
  fi
else
  # Fallback for non-unpacked standalone installers
  show_status "Step 4/5: Launching ScanSnap installer window...\n\nIf an installer wizard appears, please complete it."
  wine "${INSTALLER_EXE}" || true
  "${WINESERVER}" -k || true
  "${WINESERVER}" -w || true
fi

if [ ! -f "${SSH_EXE}" ]; then
  show_status "ERROR: PfuSshMain.exe was not found after installation.\n\nPlease check container logs (docker logs scansnap-home)."
  sleep 60
  exit 1
fi

# 5/5 Finalize document links and Linux/Wine compatibility patches
show_status "Step 5/5: Applying Windows 11, WCF, font and updater patches..."

USERS_DIR="${WINEPREFIX}/drive_c/users"
ACTIVE_USER_DIR="${USERS_DIR}/app"
LEGACY_USER_DIR="$(find "${USERS_DIR}" -mindepth 1 -maxdepth 1 -type d ! -name 'Public' ! -name 'app' 2>/dev/null | head -n 1 || true)"
if [ -n "${LEGACY_USER_DIR}" ]; then
  ACTIVE_USER_DIR="${LEGACY_USER_DIR}"
fi
APPDATA_SSH="${ACTIVE_USER_DIR}/AppData/Roaming/PFU/ScanSnap Home"
mkdir -p "${APPDATA_SSH}"

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
}

link_to_scan_dir "${ACTIVE_USER_DIR}/Documents"
link_to_scan_dir "${APPDATA_SSH}/ScanSnap Home"

"${WINESERVER}" -k || true
"${WINESERVER}" -w || true
python3 /opt/scansnap/patch_scansnap.py --runtime

echo "[firstboot] Installation and patching completed successfully."
