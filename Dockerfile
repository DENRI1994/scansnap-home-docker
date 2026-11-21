FROM ubuntu:26.04 AS shim-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

COPY src/scansnap_udp_preload.c /tmp/scansnap_udp_preload.c
RUN mkdir -p /out && \
    gcc -shared -fPIC -O2 -Wall -Wextra -o /out/libscansnap_udp.so /tmp/scansnap_udp_preload.c -ldl -lpthread && \
    strip --strip-unneeded /out/libscansnap_udp.so


FROM ubuntu:26.04 AS font-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 fonts-noto-core fonts-liberation ttfautohint && \
    rm -rf /var/lib/apt/lists/*

COPY docker/build_open_fonts.py /tmp/build_open_fonts.py
RUN python3 /tmp/build_open_fonts.py --out /out/fonts


FROM jlesage/baseimage-gui:ubuntu-26.04-v4

ARG DOCKER_IMAGE_VERSION=dev

LABEL org.opencontainers.image.title="ScanSnap Home Docker" \
      org.opencontainers.image.description="Headless ScanSnap Home container on Pure-64-bit WoW64 Wine and jlesage/baseimage-gui (contains no proprietary software)" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=bind,source=docker/strip_wine_pe.py,target=/tmp/strip_wine_pe.py \
    add-pkg \
      wine \
      wine64 \
      fonts-wine \
      fontconfig \
      x11-utils \
      procps \
      iputils-ping \
      iproute2 \
      python3 \
      ca-certificates \
      locales \
      winetricks \
      cabextract \
      unshield \
      unzip \
      curl && \
    locale-gen en_US.UTF-8 de_DE.UTF-8 && \
    python3 /tmp/strip_wine_pe.py && \
    rm -rf /usr/share/doc/* \
           /usr/share/man/* \
           /usr/share/wine/fonts/tahoma.ttf \
           /usr/share/wine/fonts/tahomabd.ttf \
           /usr/share/fonts/truetype/wine/tahoma.ttf \
           /usr/share/fonts/truetype/wine/tahomabd.ttf

RUN --mount=type=bind,source=docker/app-icon.png,target=/tmp/app-icon.png \
    install_app_icon.sh /tmp/app-icon.png

RUN set-cont-env APP_NAME "ScanSnap Home" && \
    set-cont-env KEEP_APP_RUNNING "1" && \
    set-cont-env LANG "en_US.UTF-8" && \
    set-cont-env LC_ALL "en_US.UTF-8" && \
    set-cont-env XVNC_SERVER_CUSTOM_PARAMS "-s 0" && \
    set-cont-env DOCKER_IMAGE_VERSION "${DOCKER_IMAGE_VERSION}"

COPY docker/rootfs/ /
RUN chmod +x /startapp.sh \
             /etc/cont-init.d/50-scansnap.sh \
             /etc/cont-init.d/55-openbox-wine-rules.sh \
             /etc/cont-finish.d/50-wineserver.sh \
             /opt/scansnap/scansnap_wm_daemon.py

COPY --chown=1000:1000 scripts/ntlm_auth /opt/scansnap/bin/ntlm_auth
COPY --chown=1000:1000 scripts/patch_scansnap.py /opt/scansnap/patch_scansnap.py
COPY --chown=1000:1000 scripts/unpack_is.py /opt/scansnap/unpack_is.py
COPY --chown=1000:1000 scripts/firstboot_install.sh /opt/scansnap/firstboot_install.sh
COPY --from=shim-builder --chown=1000:1000 /out/libscansnap_udp.so /opt/scansnap/lib64/libscansnap_udp.so
COPY --from=font-builder /out/fonts/ /usr/share/fonts/truetype/scansnap-ofl/

RUN chmod +x /opt/scansnap/bin/ntlm_auth \
             /opt/scansnap/patch_scansnap.py \
             /opt/scansnap/unpack_is.py \
             /opt/scansnap/firstboot_install.sh && \
    ln -sf /usr/lib/x86_64-linux-gnu/wine/wineserver /usr/local/bin/wineserver && \
    mkdir -p /opt/scansnap/wineprefix /installer && \
    chown -R 1000:1000 /opt/scansnap /installer && \
    fc-cache -f
