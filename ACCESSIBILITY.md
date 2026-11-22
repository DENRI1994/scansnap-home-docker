# Accessibility Statement

## Commitment

This project aims to make its documentation, container configuration, and custom web controls accessible and usable across browsers, operating systems, and input devices.

---

## Supported Web & Desktop Controls

The web interface is powered by [jlesage/baseimage-gui](https://github.com/jlesage/docker-baseimage-gui) and noVNC with a custom **Windows & Services** sidebar panel:

- **Viewport Scaling & Resizing:** Supports automatic remote session resizing and proportional scaling inside modern desktop browsers.
- **Light & Dark Themes:** Supports dark mode (`DARK_MODE="1"`) in the web interface and sidebar.
- **Semantic Web Controls:** Custom controls added in [scansnap-sidebar.js](docker/rootfs/opt/noVNC/app/scansnap-sidebar.js) use standard HTML `<button>` elements, descriptive `title` tooltips, and visible focus/contrast states matching Bootstrap themes.
- **Clipboard Integration:** Bidirectional clipboard sync (`WEB_HOST_CLIPBOARD_SYNC="1"`) allows copy/paste between host assistive tools and the desktop session.
- **Keyboard & Focus Assistance:** Provides keyboard shortcuts (including noVNC's clipboard/key panel) and a **Bring dialogs to front** control to recover off-screen or hidden dialogs.

---

## Known Limitations

- **Canvas-Rendered Windows UI:** ScanSnap Home is a third-party Windows WPF desktop application running under Wine and streamed to the browser via VNC onto an HTML5 `<canvas>`. Native DOM semantics, browser zoom-reflow, and OS/browser screen-reader tree inspection (ARIA) are not exposed inside the VNC `<canvas>`.
- **High Contrast & Font Scaling:** Visual text inside ScanSnap Home relies on open-source replacement TTF fonts rendered at standard Windows 96 DPI inside Wine; in-app UI layout scaling is controlled by the upstream ScanSnap Home application itself.

---

## Reporting Accessibility Barriers

If you encounter accessibility issues in our documentation, Docker configuration, or custom **Windows & Services** sidebar controls, please open an issue via [GitHub Issues](https://github.com/DENRI1994/scansnap-home-docker/issues/new/choose) describing your browser, assistive technology, and the barrier encountered.
