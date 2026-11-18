#!/usr/bin/env bash
# Construye ds-bridge-x86_64.AppImage. Ejecutar con red, en la Deck (Modo Escritorio) o en
# cualquier Linux x86_64, desde la carpeta que contiene ds_bridge.py.
#
# Variables opcionales:
#   PY_STANDALONE_URL=<url .tar.gz de python-build-standalone "install_only" x86_64-unknown-linux-gnu>
#       -> empaqueta un Python propio (AppImage 100% autocontenido).
#          Sin ella se usa el python3 del sistema (SteamOS lo incluye; el código solo usa stdlib).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${HERE}/build"
APPDIR="${BUILD}/ds-bridge.AppDir"
TOOL="${BUILD}/appimagetool-x86_64.AppImage"
export ARCH=x86_64

rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/lib/ds-bridge" "$APPDIR/usr/share/ds-bridge" "$BUILD"

# 1) Código y recursos
install -m 0755 "$HERE/ds_bridge.py"          "$APPDIR/usr/lib/ds-bridge/ds_bridge.py"
install -m 0644 "$HERE/99-ds-bridge.rules"    "$APPDIR/usr/share/ds-bridge/99-ds-bridge.rules"
install -m 0755 "$HERE/install_perms.sh"      "$APPDIR/usr/share/ds-bridge/install_perms.sh"

# 2) Python opcional embebido
if [[ -n "${PY_STANDALONE_URL:-}" ]]; then
  echo ">> Descargando Python embebido"
  curl -fL "$PY_STANDALONE_URL" -o "$BUILD/python.tar.gz"
  mkdir -p "$APPDIR/usr/python"
  tar -xzf "$BUILD/python.tar.gz" -C "$APPDIR/usr/python" --strip-components=1
fi

# 3) AppRun
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
PY="$HERE/usr/python/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
[ -n "$PY" ] || { echo "python3 no encontrado"; exit 1; }
export APPDIR="$HERE"
case "$1" in
  install-perms) shift; exec "$HERE/usr/share/ds-bridge/install_perms.sh" "$@" ;;
  *)             exec "$PY" "$HERE/usr/lib/ds-bridge/ds_bridge.py" "$@" ;;
esac
EOF
chmod +x "$APPDIR/AppRun"

# 4) .desktop + icono (PNG 256x256 generado sin dependencias externas)
cat > "$APPDIR/ds-bridge.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=DS Bridge
Comment=Puente DualShock 4 / DualSense Bluetooth
Exec=AppRun run
Icon=ds-bridge
Categories=Utility;
Terminal=false
EOF
python3 - "$APPDIR/ds-bridge.png" <<'EOF'
import sys, zlib, struct
w = h = 256
raw = b"".join(b"\0" + bytes([30, 60, 140]) * w for _ in range(h))
def chunk(t, d): c = struct.pack(">I", len(d)) + t + d; return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
open(sys.argv[1], "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                              + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
EOF
cp "$APPDIR/ds-bridge.png" "$APPDIR/.DirIcon"

# 5) appimagetool
if [[ ! -x "$TOOL" ]]; then
  echo ">> Descargando appimagetool"
  curl -fL "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" -o "$TOOL"
  chmod +x "$TOOL"
fi

# 6) Compilar (--appimage-extract-and-run evita depender de FUSE al construir)
"$TOOL" --appimage-extract-and-run "$APPDIR" "$HERE/ds-bridge-x86_64.AppImage"
chmod +x "$HERE/ds-bridge-x86_64.AppImage"

cat <<EOF

OK -> $HERE/ds-bridge-x86_64.AppImage
Pasos de uso:
  ./ds-bridge-x86_64.AppImage install-perms        # una vez
  (mando por USB)  ./ds-bridge-x86_64.AppImage capture-descriptor   # una vez por modelo
  ./ds-bridge-x86_64.AppImage install-service      # arranca siempre, también en Modo Gaming
  ./ds-bridge-x86_64.AppImage trigger --side right --effect rigid --start 3 --force 200
EOF
