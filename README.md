# ScanSnap Home in Docker (Web GUI + Wi-Fi Support)

> [!NOTE]
> **Disclaimer:** Unofficial community Docker project, **not affiliated with PFU Limited or Ricoh**.
> This repository and its published container images contain **no** ScanSnap Home software, **no** Microsoft runtime binaries, and **no** proprietary fonts. You provide the official installer downloaded directly from PFU/Ricoh for your own licensed scanner on first start.

Run **ScanSnap Home** headless on a Linux server or NAS inside Docker with a browser-based GUI ([jlesage/baseimage-gui](https://github.com/jlesage/docker-baseimage-gui): TigerVNC + NGINX + noVNC + Openbox + auto-restart), Pure-64-bit WoW64 Wine, Wi-Fi scanner discovery, working Online Update support, an integrated window & service sidebar, and clean SIL-OFL fonts.

---

## Features

- **Web GUI & Auto-Restart:** Powered by `jlesage/baseimage-gui:ubuntu-26.04-v4` with clipboard sync, dynamic browser resizing/scaling, custom icon, borderless maximized main window, and resilient process supervision (`KEEP_APP_RUNNING=1`) so closing or restarting ScanSnap Home never drops the VNC session.
- **Integrated noVNC Sidebar ("Fenster & Dienste") & X11 Self-Healing Window Watchdog:** Built into the noVNC control bar ([`scansnap-sidebar.js`](docker/rootfs/opt/noVNC/app/scansnap-sidebar.js) + [`scansnap_wm_daemon.py`](docker/rootfs/opt/scansnap/scansnap_wm_daemon.py)). Lists real open windows and modal dialogs, brings hidden or minimized dialogs to the front in one click (*Dialoge nach vorne*), shows live status and Start/Restart/Stop controls for all 6 ScanSnap background services (`ScanSnap Home`, `Scanner-Monitor`, `SshRegister`, `Task-Tray`, `Cloud-Monitor`, `Online-Update`), and automatically unmaps Wine fullscreen `clip_window` input grabs and fixes trapped Openbox dialog layers.
- **Full ScanSnap Online Update (`3.7.0` → `4.1.0+`) Support:** Configures Wine for Windows 11 (`win11`, Build `22621`), fixes WCF `NetNamedPipeBinding` loopback auth (`ntlm_auth` + `System.ServiceModel.dll` + `*.config`), fixes `SsUCommon.dll` OS version reporting, bypasses Wine's missing COM UAC elevation moniker in `ScanSnapUpdater.exe`, patches the multi-threaded WMI `Win32_Process` deadlock in `SshTerminateHomeProcess.exe` ("Quitting ScanSnap Home..."), and automatically repairs any 64-bit Visual C++ runtime DLLs written into 32-bit `syswow64` during updates (`repair_syswow64_dlls()`).
- **License-Clean ~1.1–1.3 GB Base Image:** Built strictly from Ubuntu/Wine packages, compiled C source ([`src/scansnap_udp_preload.c`](src/scansnap_udp_preload.c)), and SIL-OFL font substitutes ([`docker/build_open_fonts.py`](docker/build_open_fonts.py)) synthesized from `fonts-noto-core` (`ttfautohint`) and `fonts-liberation`.
- **Automatic First-Boot Provisioning:** Drop the official Windows offline installer (`WinSSHOfflineInstaller_*.exe`, v3.7 or v4.x) into `./installer/` (or set `SCANSNAP_INSTALLER_URL`). On first boot, the container installs Microsoft .NET Framework 4.8, unpacks the offline bundle, installs ScanSnap Home + AI + requested `OCR_LANGS` + ScanSnap Online Update, and applies all Wine compatibility patches automatically.
- **Wi-Fi Scanner Discovery (`libscansnap_udp.so`):** Filters virtual bridge interfaces (`virbr*`, `docker*`, `br-*`, `veth*`, `tun*`, `tap*`), fans out UDP `52217` broadcasts as unicast to ARP peers, and opens ports `52217`/`53220`/`55265`.
- **Persistent Host Scan Folder:** Maps your host `SCANS_DIR` directly to `C:\ScanSnapHome` and syncs both Wine Registry (`HomeFolder`) and `ScanSnapHome.db`.

---

## Quick Start (Linux CLI)

1. **Prepare config and directories:**
   ```bash
   cp .env.example .env
   mkdir -p installer scans data/ScanSnapHome
   ```
   Edit `.env` and set `SCANS_DIR` (your target folder for scanned documents), `SCANNER_IP` (your Wi-Fi scanner's IP address), and `GITHUB_REPO` (or `SCANSNAP_IMAGE`).

2. **Provide the official Ricoh / PFU Windows Offline Installer:**
   Download `WinSSHOfflineInstaller_*.exe` from Ricoh/PFU's official ScanSnap support site and place it in `./installer/`.

3. **Start the container:**
   ```bash
   docker compose up -d
   ```
   *(Use `docker compose up -d --build` if you want to build locally from `Dockerfile`.)*

4. **Monitor progress & open the GUI:**
   Open **`http://<your-host-ip>:6080/`** in your browser.
   First-boot provisioning installs `.NET 4.8`, ScanSnap Home, OCR packs, and Online Update automatically (~5–10 minutes on first start; subsequent starts take only a few seconds because the Wine prefix lives in the persistent `scansnap-prefix` Docker volume).

---

## NAS Deployment Guide (UGREEN NAS / UGOS Pro, Synology, Portainer)

On NAS appliances such as **UGREEN UGOS Pro**, **Synology Container Manager**, or **Portainer**, create a Compose **Project (Projekt)** using a prebuilt registry image (no local `Dockerfile` needed):

1. **Create the folder structure on your NAS** (example on UGREEN `volume1`):
   ```bash
   mkdir -p /volume1/docker/scansnap-home/installer \
            /volume1/docker/scansnap-home/scans \
            /volume1/docker/scansnap-home/data/ScanSnapHome
   ```
   *(You can also create `installer`, `scans`, and `data/ScanSnapHome` in the NAS File Manager under your Docker shared folder.)*

2. **Upload the official Windows Offline Installer:**
   Download `WinSSHOfflineInstaller_*.exe` from Ricoh/PFU and copy it into `/volume1/docker/scansnap-home/installer/`.

3. **Create a new Docker Project / Stack** and paste the standalone `docker-compose.yml` below (adjust `SCANNER_IP`, and verify `USER_ID`/`GROUP_ID` and volume paths match your NAS shared folder):
   ```yaml
   services:
     scansnap-home:
       image: ghcr.io/denri1994/scansnap-home-docker:latest
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
         TZ: "Europe/Berlin"
         LANG: "de_DE.UTF-8"
         LC_ALL: "de_DE.UTF-8"
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
   > [!TIP]
   > **`network_mode: host`** is strongly recommended on NAS systems so Wi-Fi scanner discovery (`UDP 52217`) works directly on your LAN. On `UGOS Pro` / `Synology`, make sure ports `6080` (Web UI), `5999` (if raw VNC is enabled), and `52217`/`53220`/`55265` do not conflict with existing services, or change `WEB_LISTENING_PORT` (e.g. `6081`).

4. **Deploy and open `http://<nas-ip>:6080/`:**
   Wait ~5–10 minutes on the very first start while `.NET 4.8` and `WinSSHOfflineInstaller_*.exe` install unattended inside the container. Once ScanSnap Home appears, open the left noVNC sidebar to access **Fenster & Dienste** if a modal dialog is ever hidden or you want to start/restart background services.

---

## Optional Password Protection

Because the container builds on `jlesage/baseimage-gui`, you can protect the Web UI without modifying the image by passing environment variables in `docker-compose.yml`:

- **Option 1 — Classic VNC Password (`VNC_PASSWORD`):**
  ```yaml
  environment:
    VNC_PASSWORD: "your-password"
  ```
  Prompts for a password in both the noVNC browser UI and raw VNC clients. *(Note: the classic RFB/VNC protocol evaluates at most the first **8 characters**.)*

- **Option 2 — Web Login Page with Arbitrary Password Length (`WEB_AUTHENTICATION`):**
  ```yaml
  environment:
    WEB_AUTHENTICATION: "1"
    WEB_AUTHENTICATION_USERNAME: "admin"
    WEB_AUTHENTICATION_PASSWORD: "your-long-secure-password"
    # Required when accessing over plain HTTP in a LAN (without SECURE_CONNECTION=1 HTTPS):
    WEB_AUTHENTICATION_ALLOW_INSECURE: "1"
  ```
  Enables NGINX `auth_request` session-cookie login at `/login/` across both noVNC and `/scansnap-api/`. Because raw VNC (`5999`) stays bound to `127.0.0.1` when `VNC_LOCALHOST_ONLY=1` (or disabled with `VNC_LISTENING_PORT=-1`), LAN clients can only enter via the authenticated web login.

---

## Configuration (`.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `SCANS_DIR` | `./scans` | Host folder mapped to `C:\ScanSnapHome` |
| `SCANNER_IP` | `192.168.1.50` | Scanner IP for ARP warmup before discovery starts |
| `OCR_LANGS` | `1,6` | Comma-separated OCR pack numbers (`1,6`, `all`, or `none`) |
| `SCANSNAP_INSTALLER_URL` | *(empty)* | Optional direct URL to download installer if `./installer/` is empty |
| `KEEP_APP_RUNNING` | `1` | Keep app supervisor loop & container alive when ScanSnap Home exits or restarts |
| `TZ` / `LANG` / `LC_ALL` | `Europe/Berlin` / `de_DE.UTF-8` | Timezone and Windows/Wine UI language (set e.g. `en_US.UTF-8` for English UI) |
| `WEB_LISTENING_PORT` | `6080` | noVNC web interface port (`network_mode: host`) |
| `VNC_LISTENING_PORT` | `5999` | Raw VNC port (`-1` to disable, localhost-only by default) |
| `VNC_LOCALHOST_ONLY` | `1` | Restrict direct VNC port to `127.0.0.1` |
| `VNC_PASSWORD` | *(empty)* | Optional classic VNC password (max 8 characters evaluated) |
| `WEB_AUTHENTICATION` | `0` | Set `1` to require NGINX `/login/` username/password authentication |
| `DISPLAY_WIDTH` / `DISPLAY_HEIGHT` | `1440` / `900` | Virtual X11 display resolution |
| `DARK_MODE` | `0` | `1` enables dark mode in the web sidebar |

---

## Automated CI/CD Publishing (GitHub Actions)

The included workflow [`.github/workflows/publish.yml`](.github/workflows/publish.yml) builds, smoke-tests, and publishes the image automatically:

- **Triggers:** Every push to `main`, release tags (`v*`, e.g. `v26.11.1`), manual dispatch, and a **weekly Sunday schedule (`04:00 UTC`)** to pick up upstream Ubuntu 26.04, Wine, and `jlesage/baseimage-gui` security updates.
- **GitHub Container Registry (`ghcr.io`):** Works out-of-the-box with zero extra secrets via `GITHUB_TOKEN`. Ensure *Workflow permissions → Read and write permissions* is enabled under Repository Settings → Actions → General.
- **Docker Hub (`docker.io`, optional):** Add repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` in GitHub Settings → Secrets and variables → Actions. The workflow automatically pushes to both `ghcr.io/<owner>/<repo>` and `docker.io/<user>/scansnap-home` whenever both secrets are present.

---

## Updating

To pull a newer base image (Ubuntu / Wine / VNC security updates) without touching your ScanSnap installation, scans, or profiles:

```bash
docker compose pull && docker compose up -d
```

For ScanSnap Home application updates itself, use **ScanSnap Online Update** directly inside the GUI (or launch **Online-Update** from the noVNC *Fenster & Dienste* sidebar).

---

## License

Code, build scripts, and original icon in this repository are released under the [MIT License](LICENSE). Third-party system packages retain their respective open-source licenses (Noto & Liberation fonts under SIL OFL 1.1; Wine under LGPL-2.1+).
