#!/usr/bin/env bash
set -euo pipefail

export WINEPREFIX=/opt/scansnap/wineprefix
export LANG="${LANG:-de_DE.UTF-8}"
export LC_ALL="${LC_ALL:-${LANG}}"
export PATH="/opt/scansnap/bin:${PATH}"
export SCAN_FOLDER_WIN="${SCAN_FOLDER_WIN:-C:\\ScanSnapHome}"

SSH_DIR='C:\Program Files (x86)\PFU\ScanSnap\Home'
SSH_EXE="${WINEPREFIX}/drive_c/Program Files (x86)/PFU/ScanSnap/Home/PfuSshMain.exe"
UPDATER_REGEX='ScanSnapUpdater|SsUWatcher|SsUSetting|WinSSHome|WinOnlineUpdate|WinScanSnap|setup\.exe|msiexec|IDriver|ISSetup'

# Run unattended first-boot setup if ScanSnap Home is not yet installed in the prefix volume
if [ ! -f "${SSH_EXE}" ] && [ -x /opt/scansnap/firstboot_install.sh ]; then
  /opt/scansnap/firstboot_install.sh
fi

export LD_LIBRARY_PATH="/opt/scansnap/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export LD_PRELOAD="libscansnap_udp.so${LD_PRELOAD:+:${LD_PRELOAD}}"

rm -f /tmp/scansnap_main_paused /tmp/scansnap_reg_paused /tmp/scansnap_mon_paused

while true; do
  while [ -f /tmp/scansnap_main_paused ]; do
    sleep 1
  done

  # If ScanSnap Online Update closed ScanSnap Home to update files, wait until update completes and re-verify patches
  if pgrep -fi "${UPDATER_REGEX}" >/dev/null 2>&1; then
    while pgrep -fi "${UPDATER_REGEX}" >/dev/null 2>&1; do
      sleep 2
    done
    python3 /opt/scansnap/patch_scansnap.py --runtime || true
  fi

  if [ -f /tmp/scansnap_main_paused ]; then
    continue
  fi

  if ! pgrep -fi 'PFU\\ScanSnap\\Home\\PfuSshMain\.exe' >/dev/null 2>&1; then
    # Warm ARP entry for the Wi-Fi scanner before Wine UDP discovery starts
    if [ -n "${SCANNER_IP:-}" ]; then
      ping -c 1 -W 1 "${SCANNER_IP}" >/dev/null 2>&1 &
    fi

    if [ ! -f /tmp/scansnap_reg_paused ] && ! pgrep -fi 'PFU\\ScanSnap\\Home\\SshRegister\.exe' >/dev/null 2>&1; then
      wine "${SSH_DIR}\\SshRegister.exe" >/tmp/scansnap_sshregister.log 2>&1 &
      sleep 4
    fi

    if [ ! -f /tmp/scansnap_mon_paused ] && ! pgrep -fi 'PFU\\ScanSnap\\Home\\PfuSsMon\.exe' >/dev/null 2>&1; then
      wine "${SSH_DIR}\\PfuSsMon.exe" >/tmp/scansnap_pfussmon.log 2>&1 &
      sleep 5
    fi

    if [ ! -f /tmp/scansnap_main_paused ] && ! pgrep -fi 'PFU\\ScanSnap\\Home\\PfuSshMain\.exe' >/dev/null 2>&1; then
      wine "${SSH_DIR}\\PfuSshMain.exe" || true
    fi
  fi
  sleep 1
done
