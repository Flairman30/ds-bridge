#!/usr/bin/env bash
# Construye "DS-Bridge-decky.zip" listo para: Decky -> Modo desarrollador -> Instalar plugin desde ZIP.
# Requiere Node.js >= 16.14, pnpm y red (para pnpm install). Ejecutar en la Deck (escritorio) o en un PC.
set -euo pipefail
cd "$(dirname "$0")"
cp ../ds_bridge.py ../99-ds-bridge.rules defaults/
cp ../LICENSE LICENSE
pnpm install
pnpm run build
STAGE="$(mktemp -d)"; NAME="DS Bridge"
mkdir -p "$STAGE/$NAME"
cp -r dist defaults main.py plugin.json package.json LICENSE "$STAGE/$NAME/"
rm -f DS-Bridge-decky.zip
( cd "$STAGE" && zip -qr "$OLDPWD/DS-Bridge-decky.zip" "$NAME" )
rm -rf "$STAGE"
echo "OK -> $(pwd)/DS-Bridge-decky.zip"
