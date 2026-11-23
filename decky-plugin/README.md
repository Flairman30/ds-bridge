# DS Bridge – Decky plugin (experimental, untested)
Panel for Game Mode to start/stop the ds-bridge daemon, install udev permissions and capture the USB descriptor.
Build: `./build_zip.sh` (needs Node, pnpm, network) -> `DS-Bridge-decky.zip`.
Install: Decky settings -> enable Developer mode -> install plugin from ZIP.
The backend runs as root (`"flags": ["root"]`) to install udev rules; the daemon runs as the Deck user.
