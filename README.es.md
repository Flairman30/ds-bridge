# ds-bridge (resumen en español)

Puente experimental Bluetooth → "USB virtual" para mandos **DualShock 4 y DualSense** en **SteamOS**, empaquetado como AppImage
(todo en `/home`, sin tocar el sistema raíz de solo lectura).

> ⚠️ **Estado: experimental y sin probar en hardware real.** La traducción HID está implementada; el **audio por Bluetooth es un stub**.
> Proyecto no afiliado a Sony.

**Uso rápido:** `./build_appimage.sh` → `install-perms` → `capture-descriptor` (mando por USB) → `install-service` → emparejar por BT
y desactivar Steam Input en el juego. Detalles técnicos y pendientes en el README en inglés y en `docs/PROTOCOL_NOTES.md`.

**Se busca ayuda con:** pruebas en hardware, formato de audio/háptica por BT (captura con `btmon`), verificar efectos de gatillo.
