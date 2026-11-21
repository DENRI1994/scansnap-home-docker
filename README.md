# ScanSnap Home in Docker (Web GUI + Wi-Fi Support)

> **Disclaimer & Legal Notice:**  
> This is an **unofficial community Docker project** and is **not affiliated with, endorsed by, or sponsored by PFU Limited or Ricoh Company, Ltd.**  
> *ScanSnap* and *ScanSnap Home* are registered trademarks of PFU Limited. *Windows* and *.NET Framework* are trademarks of Microsoft Corporation.  
> **No proprietary software or fonts included:** This repository and its published container images (`ghcr.io/denri1994/scansnap-home-docker` and `denri1994/scansnap-home`) contain **no** ScanSnap Home installers, **no** Microsoft binaries, and **no** proprietary fonts. You must download the official installer directly from PFU / Ricoh and use it exclusively in accordance with your valid hardware and software license.

Run **ScanSnap Home** on your NAS or Linux home server in Docker and access the full desktop application directly in any modern web browser, with Wi-Fi scanner discovery, automatic first-boot installation, working in-app Online Updates, and persistent document storage.

---

## Key Features

- **Browser Web GUI (`noVNC`):** Control ScanSnap Home from any browser at `http://<your-server-ip>:6080/` with dynamic window resizing, clipboard sync, light/dark web sidebar theme, and automatic app supervision (`KEEP_APP_RUNNING=1`).
- **Unattended First-Boot Setup:** Drop the official PFU / Ricoh Windows Offline Installer (`WinSSHOfflineInstaller_*.exe`, v3.7 or v4.x) into your `installer` folder (or provide `SCANSNAP_INSTALLER_URL`). On first start, the container installs required runtime components, ScanSnap Home, OCR packs, and Online Update automatically.
- **Wi-Fi Scanner Discovery (`network_mode: host`):** Automatic LAN discovery for wireless ScanSnap scanners without USB passthrough.
- **Built-in "Windows & Services" Sidebar:** Built directly into the left noVNC control panel to bring any hidden or minimized dialog window to the front in one click (*Bring dialogs to front*) and to start, stop, or restart ScanSnap background services (`ScanSnap Home`, `Scanner Monitor`, `SshRegister`, `Task Tray`, `Cloud Monitor`, `Online Update`) without disconnecting VNC.
- **In-App ScanSnap Online Update:** Supports updating ScanSnap Home (e.g. `3.7.0` → `4.1.0+`) right inside the GUI.
- **Persistent Scans & Settings:** Your scanned documents are written directly to a host folder of your choice, while preferences, profiles, and updates persist in Docker volumes / mapped folders.
- **Open-Source Font Replacements:** Uses crisp open-source SIL-OFL fonts (`Noto Sans`, `Liberation`) mapped for Windows UI typography.

---

## Quick Start — Option 1: NAS Setup (UGREEN UGOS Pro, Synology, Portainer)

Create a new Docker Compose **Project** / **Stack** using the prebuilt image from Docker Hub or GitHub Container Registry:

1. **Create three folders on your NAS** (example on UGREEN `volume1`):
   ```bash
   mkdir -p /volume1/docker/scansnap-home/installer \
            /volume1/docker/scansnap-home/scans \
            /volume1/docker/scansnap-home/data/ScanSnapHome
   ```
   *(You can also create `installer`, `scans`, and `data/ScanSnapHome` using your NAS File Manager.)*

2. **Download the official PFU / Ricoh Offline Installer:**  
   Download the Windows offline installer (`WinSSHOfflineInstaller_*.exe`) from the official Ricoh / PFU ScanSnap support website and place it into `/volume1/docker/scansnap-home/installer/`.

3. **Create the Docker Project / Stack** with the configuration below (replace `SCANNER_IP` with your scanner's IP address, set `TZ` / `LANG` / `LC_ALL` if desired, and adjust the `/volume1/docker/...` paths to match your NAS):

   ```yaml
   services:
     scansnap-home:
       image: denri1994/scansnap-home:latest
       # Alternatively from GitHub Container Registry:
       # image: ghcr.io/denri1994/scansnap-home-docker:latest
       container_name: scansnap-home
       network_mode: host
       restart: unless-stopped
       environment:
         USER_ID: "1000"
         GROUP_ID: "1000"
         KEEP_APP_RUNNING: "1"
         WEB_LISTENING_PORT: "6080"
         VNC_LISTENING_PORT: "5999"
         VNC_LOCALHOST_ONLY: "1"
         DISPLAY_WIDTH: "1440"
         DISPLAY_HEIGHT: "900"
         DARK_MODE: "0"
         WEB_HOST_CLIPBOARD_SYNC: "1"
         SCANNER_IP: "192.168.1.50"
         SCAN_FOLDER_WIN: 'C:\ScanSnapHome'
         OCR_LANGS: "1,6"
         TZ: "UTC"
         LANG: "en_US.UTF-8"     # Use de_DE.UTF-8 for German UI
         LC_ALL: "en_US.UTF-8"   # Use de_DE.UTF-8 for German UI
         # Optional password protection (see section below):
         # VNC_PASSWORD: "your-password"
         # WEB_AUTHENTICATION: "1"
         # WEB_AUTHENTICATION_USERNAME: "admin"
         # WEB_AUTHENTICATION_PASSWORD: "your-long-secure-password"
         # WEB_AUTHENTICATION_ALLOW_INSECURE: "1"
       volumes:
         - scansnap-prefix:/opt/scansnap/wineprefix
         - /volume1/docker/scansnap-home/data/ScanSnapHome:/opt/scansnap/wineprefix/drive_c/users/app/AppData/Roaming/PFU/ScanSnap Home
         - /volume1/docker/scansnap-home/scans:/opt/scansnap/wineprefix/drive_c/ScanSnapHome
         - /volume1/docker/scansnap-home/installer:/installer:ro

   volumes:
     scansnap-prefix:
   ```

   > **Tip (`network_mode: host`):** Host networking is recommended so your NAS can discover Wi-Fi ScanSnap scanners directly on your LAN. Make sure port `6080` is free on your NAS, or change `WEB_LISTENING_PORT` (for example to `"6081"`).

4. **Start and open `http://<nas-ip>:6080/`:**  
   The very first start takes **~5–10 minutes** while the unattended installation runs inside the container (you will see progress messages in the browser window). Subsequent starts take only a few seconds.

---

## Quick Start — Option 2: Linux CLI (`docker compose`)

1. Clone the repository and prepare your directories:
   ```bash
   git clone https://github.com/DENRI1994/scansnap-home-docker.git
   cd scansnap-home-docker
   cp .env.example .env
   mkdir -p installer scans data/ScanSnapHome
   ```
2. Edit `.env` (for example `SCANNER_IP`, `SCANS_DIR`, `TZ`, `LANG`, `LC_ALL`).
3. Download the official `WinSSHOfflineInstaller_*.exe` from PFU / Ricoh and place it in `./installer/`.
4. Start the container and open **`http://<your-host-ip>:6080/`**:
   ```bash
   docker compose up -d
   ```

---

## UI Language & Timezone

By default, ScanSnap Home starts in **English** (`en_US.UTF-8`, `UTC`).  
To switch the ScanSnap Home interface to another supported language (for example **German**) and local timezone, set:

```yaml
environment:
  TZ: "Europe/Berlin"
  LANG: "de_DE.UTF-8"
  LC_ALL: "de_DE.UTF-8"
```

---

## Optional Password Protection

If your NAS or server is reachable on a shared network, you can protect the Web GUI with environment variables:

- **Option 1 — Classic VNC Password (`VNC_PASSWORD`):**
  ```yaml
  environment:
    VNC_PASSWORD: "your-password"
  ```
  Prompts for a password in noVNC and VNC clients. *(Note: the classic VNC/RFB protocol evaluates at most the first **8 characters**.)*

- **Option 2 — Web Login Page with Arbitrary Password Length (`WEB_AUTHENTICATION`):**
  ```yaml
  environment:
    WEB_AUTHENTICATION: "1"
    WEB_AUTHENTICATION_USERNAME: "admin"
    WEB_AUTHENTICATION_PASSWORD: "your-long-secure-password"
    # Required when accessing over plain HTTP on your LAN (without HTTPS):
    WEB_AUTHENTICATION_ALLOW_INSECURE: "1"
  ```
  Protects the web interface and sidebar API behind a login page with session cookies. Keep `VNC_LOCALHOST_ONLY: "1"` (or set `VNC_LISTENING_PORT: "-1"`) so unauthenticated clients cannot bypass the web login via raw VNC.

---

## Configuration Variables

| Variable | Default | Description |
| --- | --- | --- |
| `SCANS_DIR` | `./scans` | Host folder mapped to `C:\ScanSnapHome` for scanned PDFs/images |
| `SCANNER_IP` | `192.168.1.50` | Scanner IP address on your LAN for faster Wi-Fi discovery |
| `OCR_LANGS` | `1,6` | OCR language pack IDs to install (`1,6`, `all`, or `none`) |
| `SCANSNAP_INSTALLER_URL` | *(empty)* | Optional direct URL to fetch the offline installer if `./installer/` is empty |
| `KEEP_APP_RUNNING` | `1` | Keeps the container alive when ScanSnap Home is closed or restarted |
| `TZ` / `LANG` / `LC_ALL` | `UTC` / `en_US.UTF-8` | Timezone and application language (set e.g. `de_DE.UTF-8` for German) |
| `WEB_LISTENING_PORT` | `6080` | Browser Web UI port (`network_mode: host`) |
| `VNC_LISTENING_PORT` | `5999` | Raw VNC port (`-1` to disable) |
| `VNC_LOCALHOST_ONLY` | `1` | Binds raw VNC port only to `127.0.0.1` |
| `VNC_PASSWORD` | *(empty)* | Optional classic VNC password (max 8 characters evaluated) |
| `WEB_AUTHENTICATION` | `0` | Set to `1` to enable the web login screen |
| `DISPLAY_WIDTH` / `DISPLAY_HEIGHT` | `1440` / `900` | Initial virtual display resolution (resizes automatically with browser) |
| `DARK_MODE` | `0` | Set to `1` for dark mode in the web sidebar |
| `USER_ID` / `GROUP_ID` | `1000` / `1000` | Host UID/GID owning files written to `scans` and `data/ScanSnapHome` |

---

## Using the Sidebar & Updating

- **Windows & Services Sidebar:** Click the tab on the left edge of the browser window to expand the noVNC sidebar and open **Windows & Services**. You can click any listed window to focus it, click **Bring dialogs to front** if a confirmation popup is hidden behind another window, or start/stop/restart background services (`ScanSnap Home`, `Scanner Monitor`, `SshRegister`, `Task Tray`, `Cloud Monitor`, `Online Update`).
- **ScanSnap Application Updates:** Open **ScanSnap Online Update** inside ScanSnap Home (or start **Online Update** from the sidebar). Your installed version, scanner settings, and scanned documents are preserved.
- **Container / Base Image Updates:** Pull newer Linux/Wine security updates anytime without losing your ScanSnap installation or scans:
  ```bash
  docker compose pull && docker compose up -d
  ```

---

## Source Code, License & Third-Party Notices

- **Source & Issues:** https://github.com/DENRI1994/scansnap-home-docker
- **Project License:** All scripts, configuration files, C shim source code, and the container icon in this repository are released under the [MIT License](https://github.com/DENRI1994/scansnap-home-docker/blob/main/LICENSE).
- **Third-Party Software:** Container base packages retain their own open-source licenses, including [jlesage/baseimage-gui](https://github.com/jlesage/docker-baseimage-gui) (MIT), Wine (LGPL-2.1+), and Noto / Liberation fonts (SIL Open Font License 1.1). Users are solely responsible for complying with PFU / Ricoh and Microsoft End User License Agreements (EULAs) for the software they supply at runtime.
