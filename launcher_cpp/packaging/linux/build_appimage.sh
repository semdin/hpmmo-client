#!/bin/bash
# Builds HPMMO_Launcher-x86_64.AppImage inside the packaging/linux/Dockerfile
# image. Run by ci_build_launcher.sh:
#   build_appimage.sh <launcher_cpp source dir> <launcher version> <out dir>
set -euo pipefail
src="$1"
version="$2"
out="$3"
build=/tmp/launcher-build
appdir=/tmp/AppDir

rm -rf "$build" "$appdir"
cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DHPMMO_LAUNCHER_VERSION="$version" -DFETCHCONTENT_SOURCE_DIR_SDL3=/opt/sdl3 >/dev/null
ninja -C "$build" HPMMO_Launcher >/dev/null

bin="$build/HPMMO_Launcher"
strip "$bin"
# glibc is the only dynamic dependency besides libdl/libm/libpthread/libc.
needed="$(objdump -p "$bin" | awk '/NEEDED/ {print $2}' | sort | tr '\n' ' ')"
echo "NEEDED: $needed"
for lib in $needed; do
    case "$lib" in
        libc.so.6|libm.so.6|libdl.so.2|libpthread.so.0|ld-linux-x86-64.so.2) ;;
        *) echo "unexpected dynamic dependency: $lib" >&2; exit 1 ;;
    esac
done
max_glibc="$(objdump -T "$bin" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
echo "requires $max_glibc"

mkdir -p "$appdir/usr/bin"
cp "$bin" "$appdir/usr/bin/HPMMO_Launcher"
cp "$src/assets/hpmmo_256.png" "$appdir/hpmmo-launcher.png"
cp "$src/packaging/linux/hpmmo-launcher.desktop" "$appdir/hpmmo-launcher.desktop"
ln -s usr/bin/HPMMO_Launcher "$appdir/AppRun"

mkdir -p "$out"
ARCH=x86_64 /opt/appimagetool/AppRun --no-appstream --runtime-file /opt/runtime-x86_64 \
    "$appdir" "$out/HPMMO_Launcher-x86_64.AppImage" >/dev/null 2>&1
chmod 755 "$out/HPMMO_Launcher-x86_64.AppImage"
ls -la "$out/HPMMO_Launcher-x86_64.AppImage"
