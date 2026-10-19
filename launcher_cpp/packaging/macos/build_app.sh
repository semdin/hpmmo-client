#!/bin/bash
# Builds the macOS launcher on a macOS host (GitHub-hosted runner):
#   build_app.sh <launcher_cpp dir> <launcher version> <out dir>
# Produces in <out dir>:
#   HPMMO_Launcher-macos.zip   "HPMMO Launcher.app" for the first download
#   HPMMO_Launcher-macos       the bare universal Mach-O: the self-update payload
#                              (swapped into the .app, which is then re-signed)
# Universal (x86_64 + arm64), ad-hoc signed (no Apple Developer certificate):
# a downloaded .app needs right-click -> Open once; files the launcher fetches
# itself carry no quarantine flag.
set -euo pipefail
src="$(cd "$1" && pwd)"
version="$2"
out="$3"
build="$(mktemp -d)/build"

cmake -S "$src" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 \
    -DHPMMO_LAUNCHER_VERSION="$version" >/dev/null
ninja -C "$build" HPMMO_Launcher HPMMO_UpdaterCLI >/dev/null
lipo -info "$build/HPMMO_Launcher"
otool -L "$build/HPMMO_Launcher"

app="$build/HPMMO Launcher.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$build/HPMMO_Launcher" "$app/Contents/MacOS/HPMMO_Launcher"
sed "s/@VERSION@/$version/g" "$src/packaging/macos/Info.plist.in" > "$app/Contents/Info.plist"

iconset="$build/hpmmo.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256; do
    sips -z "$size" "$size" "$src/assets/hpmmo_256.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    if [ "$double" -le 256 ]; then
        sips -z "$double" "$double" "$src/assets/hpmmo_256.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
    fi
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/hpmmo.icns"

codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"

mkdir -p "$out"
rm -f "$out/HPMMO_Launcher-macos.zip"
ditto -c -k --keepParent "$app" "$out/HPMMO_Launcher-macos.zip"
cp "$app/Contents/MacOS/HPMMO_Launcher" "$out/HPMMO_Launcher-macos"
cp "$build/HPMMO_UpdaterCLI" "$out/HPMMO_UpdaterCLI-macos"
ls -la "$out"
