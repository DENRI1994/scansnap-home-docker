# Contributing to ScanSnap Home in Docker

Thank you for your interest in contributing! Every bug report, documentation improvement, and pull request helps keep this container reliable across NAS and Linux hosts.

Please review our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

---

## Reporting Bugs & Requesting Features

- Use the [Bug Report](https://github.com/DENRI1994/scansnap-home-docker/issues/new?template=bug_report.yml) form for reproducible defects, Wine/UI regressions, or NAS setup issues. Include container logs and sanitized app logs (`SSHAppLog.txt`, `SsView.log`).
- Use the [Feature Request](https://github.com/DENRI1994/scansnap-home-docker/issues/new?template=feature_request.yml) form for new configuration options or workflow improvements.
- For security issues, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

---

## Repository Hygiene & Legal Requirements (Strictly Enforced)

To keep the repository clean, legal, and safe for automated container builds:

1. **No Proprietary Binaries or Fonts:** Never commit PFU/Ricoh or Microsoft installers (`.exe`, `.msi`, `.dmg`), extracted DLLs/executables, OCR language packs, or proprietary font files (`.ttf`, `.otf`).
2. **No Personal Data or Secrets:** Never commit `.env` files, host filesystem paths containing personal usernames, private LAN IPs, scanner serial numbers, passwords, or real scanned documents.
3. **English Everywhere:** Keep all code, comments, commit messages, UI strings, scripts, and documentation in clear **English**.

---

## Local Development & Verification

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/DENRI1994/scansnap-home-docker.git
   cd scansnap-home-docker
   cp .env.example .env
   ```
2. Run static syntax checks before committing changes:
   ```bash
   python3 -m py_compile scripts/*.py docker/build_open_fonts.py docker/strip_wine_pe.py docker/rootfs/opt/scansnap/scansnap_wm_daemon.py
   bash -n docker/rootfs/startapp.sh docker/rootfs/etc/cont-init.d/*.sh docker/rootfs/etc/cont-finish.d/*.sh scripts/firstboot_install.sh
   node --check docker/rootfs/opt/noVNC/app/scansnap-sidebar.js
   ```
3. Build and test locally with Docker Compose:
   ```bash
   docker compose build
   docker compose up -d
   ```
   Verify that:
   - The web UI loads over HTTP (`noVNC` + `Windows & Services` sidebar).
   - Existing installations auto-heal idempotently on restart (`50-scansnap.sh` / `patch_scansnap.py --runtime`).
   - Temporary test containers, caches (`__pycache__`), and test volumes are cleaned up before committing.

---

## Pull Request Process

1. Create a focused feature/fix branch from `main`.
2. Keep changes minimal, well-commented, and free of duplicated logic.
3. Complete the checklist in [PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).
4. Ensure GitHub Actions (`Build, Test & Publish`) passes on your pull request.

By submitting a pull request, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
