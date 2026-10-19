# Build environment for the Linux launcher AppImage.
#
# Ubuntu 22.04 on purpose: its glibc (2.35) is the oldest the launcher
# requires, so the AppImage starts on Ubuntu 22.04+, Debian 12, Fedora,
# Arch/SteamOS. libstdc++ is linked statically and libcurl is loaded at run
# time, so glibc is the only system library the binary itself needs.
# Every download is pinned by version and sha256.
FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        build-essential cmake ninja-build pkg-config file ca-certificates curl binutils \
        libcurl4-openssl-dev \
        libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev libxss-dev \
        libxtst-dev libxkbcommon-dev libwayland-dev wayland-protocols libegl-dev libgl-dev \
        libdecor-0-dev libdbus-1-dev libudev-dev \
    && rm -rf /var/lib/apt/lists/*

# SDL3 source (the same pin as CMakeLists.txt; used via FETCHCONTENT_SOURCE_DIR_SDL3).
RUN curl -fsSL -o /tmp/sdl3.tar.gz https://github.com/libsdl-org/SDL/releases/download/release-3.4.16/SDL3-3.4.16.tar.gz \
    && echo "7322236cd12090c3eb40b9728be4d49c76f66ad17d04369584d4ecad5cf77c68  /tmp/sdl3.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/sdl3 && tar -xzf /tmp/sdl3.tar.gz -C /opt/sdl3 --strip-components=1 && rm /tmp/sdl3.tar.gz

# appimagetool 1.9.1 (extracted: no FUSE inside the container) + type2 runtime 20251108.
RUN curl -fsSL -o /tmp/appimagetool https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
    && echo "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0  /tmp/appimagetool" | sha256sum -c - \
    && chmod +x /tmp/appimagetool && cd /opt && /tmp/appimagetool --appimage-extract >/dev/null \
    && mv /opt/squashfs-root /opt/appimagetool && rm /tmp/appimagetool \
    && curl -fsSL -o /opt/runtime-x86_64 https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
    && echo "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d  /opt/runtime-x86_64" | sha256sum -c -
