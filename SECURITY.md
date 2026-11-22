# Security Policy

## Supported Versions

Only the latest container image built from the `main` branch (`latest` tag and the current minor/date tag) receives security and bug fixes. Older pinned digests are unsupported.

| Version | Supported |
| --- | --- |
| `latest` (`main`) | Yes |
| Older releases / digests | No |

---

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub Issues, discussions, or pull requests.

Report potential vulnerabilities privately using:

- [GitHub Security Advisories (Private Vulnerability Reporting)](https://github.com/DENRI1994/scansnap-home-docker/security/advisories/new)

Please include:
- A clear description of the issue and affected file(s) or image layer,
- Steps to reproduce or proof-of-concept configuration,
- Potential impact (e.g., container escape, privilege escalation, auth bypass, XSS in noVNC sidebar).

---

## Scope & Third-Party Components

This repository's security scope covers:
- `Dockerfile`, container entrypoint/init/finish scripts (`docker/rootfs/`),
- Compatibility/patching scripts (`scripts/`),
- The X11 window-management daemon (`scansnap_wm_daemon.py`), UDP preload shim (`src/scansnap_udp_preload.c`), and `noVNC` sidebar extension (`scansnap-sidebar.js`).

Vulnerabilities in upstream components—including Ubuntu packages, Wine, `jlesage/baseimage-gui`, noVNC, .NET Framework, or the user-supplied PFU/Ricoh ScanSnap Home software—should be reported directly to their respective maintainers/vendors. Weekly automated rebuilds in CI pull updated upstream base/OS packages.

---

## Deployment Hardening Recommendations

ScanSnap Home uses `network_mode: host` for Wi-Fi scanner discovery, which exposes `WEB_LISTENING_PORT` (default `6080`) on host interfaces. Follow these best practices:

- **Do not expose port `6080` directly to the public internet.** Keep it on your trusted LAN/VPN or behind an authenticated HTTPS reverse proxy.
- **Enable authentication** when on shared networks: set `WEB_AUTHENTICATION="1"` with strong `WEB_AUTHENTICATION_USERNAME` and `WEB_AUTHENTICATION_PASSWORD` values (plus HTTPS or `WEB_AUTHENTICATION_ALLOW_INSECURE="1"` strictly on private LANs).
- **Keep raw VNC restricted:** retain `VNC_LOCALHOST_ONLY="1"` or set `VNC_LISTENING_PORT="-1"` so unauthenticated clients cannot bypass the web login via VNC.
- **Run with non-root host ownership:** keep `USER_ID` / `GROUP_ID` matched to your non-privileged host user (e.g. `1000:1000`).
