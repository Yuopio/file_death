#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$(mktemp -d)"
APP_DIR="$BUILD_DIR/Shimeji.AppDir"
APPIMAGE_TOOL="$BUILD_DIR/appimagetool-x86_64.AppImage"

cleanup() {
    rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

cd "$ROOT_DIR"
mkdir -p dist

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    binutils \
    ca-certificates \
    curl \
    file \
    libatk1.0-0 \
    libcairo2 \
    libdbus-1-3 \
    libegl1 \
    libfontconfig1 \
    libfreetype6 \
    libgdk-pixbuf-2.0-0 \
    libglib2.0-0 \
    libgl1 \
    libgtk-3-0 \
    libharfbuzz0b \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libxkbcommon-x11-0 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-shape0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libx11-xcb1 \
    squashfs-tools

python -m pip install --no-cache-dir --upgrade pip
python -m pip install --no-cache-dir PySide6-Essentials PyInstaller

DATA_ARGS=(--add-data "$ROOT_DIR/assets:assets" --add-data "$ROOT_DIR/words.txt:.")
for sprite in "$ROOT_DIR"/*.png; do
    DATA_ARGS+=(--add-data "$sprite:.")
done

pyinstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name Shimeji \
    --distpath "$BUILD_DIR/dist" \
    --workpath "$BUILD_DIR/work" \
    --specpath "$BUILD_DIR" \
    "${DATA_ARGS[@]}" \
    "$ROOT_DIR/shimeji.py"

mkdir -p \
    "$APP_DIR" \
    "$APP_DIR/usr/bin" \
    "$APP_DIR/usr/share/applications" \
    "$APP_DIR/usr/share/icons/hicolor/256x256/apps"

cp "$BUILD_DIR/dist/Shimeji" "$APP_DIR/usr/bin/Shimeji"
cp "$ROOT_DIR/packaging/linux/shimeji.desktop" "$APP_DIR/usr/share/applications/shimeji.desktop"
cp "$ROOT_DIR/stay1.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/shimeji.png"
cp "$ROOT_DIR/packaging/linux/shimeji.desktop" "$APP_DIR/shimeji.desktop"
cp "$ROOT_DIR/stay1.png" "$APP_DIR/shimeji.png"

cat > "$APP_DIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Shimeji" "$@"
APPRUN
chmod +x "$APP_DIR/AppRun" "$APP_DIR/usr/bin/Shimeji"

curl -L --fail --retry 3 \
    -o "$APPIMAGE_TOOL" \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x "$APPIMAGE_TOOL"

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGE_TOOL" \
    "$APP_DIR" \
    "$ROOT_DIR/dist/Shimeji-x86_64.AppImage"

chmod +x "$ROOT_DIR/dist/Shimeji-x86_64.AppImage"
echo "Built: $ROOT_DIR/dist/Shimeji-x86_64.AppImage"