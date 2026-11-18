#!/usr/bin/env bash
# Permisos para ds-bridge en SteamOS.
#   ./install_perms.sh            -> instala reglas udev en /etc (persisten; reaplicar si una
#                                    actualización de SteamOS las borra)
#   ./install_perms.sh --temporary -> solo ACLs sobre los nodos actuales (se pierden al reiniciar
#                                    o reconectar el mando). No toca /etc.
# NO hace falta `steamos-readonly disable`: /etc es escribible en SteamOS.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"

if [[ "${1:-}" == "--temporary" ]]; then
  sudo modprobe uhid || true
  sudo setfacl -m "u:${USER_NAME}:rw" /dev/uhid
  for n in /dev/hidraw*; do sudo setfacl -m "u:${USER_NAME}:rw" "$n"; done
  echo "ACLs temporales aplicadas."
  exit 0
fi

RULES_SRC="${HERE}/99-ds-bridge.rules"
[[ -f "$RULES_SRC" ]] || RULES_SRC="${APPDIR:-$HERE}/usr/share/ds-bridge/99-ds-bridge.rules"

sudo install -m 0644 "$RULES_SRC" /etc/udev/rules.d/99-ds-bridge.rules
echo uhid | sudo tee /etc/modules-load.d/ds-bridge.conf >/dev/null
sudo modprobe uhid || true
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=misc
echo "Listo. Reconecta el mando y comprueba:  ls -l /dev/uhid  (debe mostrar ACL '+')."
