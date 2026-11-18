# ds-bridge

Experimental Bluetooth → "virtual USB" bridge for **DualShock 4** and **DualSense** on **SteamOS / Steam Deck**,
packaged as a self-contained AppImage (lives entirely in `/home`, no changes to the read-only rootfs).

> ⚠️ **Status: experimental, untested on real hardware.** The HID translation layer is implemented from
> kernel driver (`hid-sony`, `hid-playstation`) behaviour; the **Bluetooth audio path is a stub**.
> This is a call for contributors, not a finished product. Not affiliated with or endorsed by Sony.

## Goal
Games running under Proton (e.g. Ghost of Tsushima, Spider-Man) expect a Sony pad on **USB** so they can use
the speaker, mic, haptics and adaptive triggers. Over Bluetooth, Linux exposes a plain gamepad. ds-bridge:

1. Reads the real BT `hidraw` node (`054c:05c4`, `054c:09cc`, `054c:0ce6`, `054c:0df2`).
2. Creates a **UHID** device that looks like the same pad on the **USB bus**, using the real USB report descriptor.
3. Translates reports both ways (input BT→USB, output USB→BT with CRC32, feature reports).
4. Lets you pin **adaptive-trigger** effects through a control socket.
5. Creates PipeWire/Pulse virtual devices ("Wireless Controller", "Wireless Controller Mic") and captures their audio.

## What works / what doesn't
| Feature | State |
|---|---|
| BT→USB input translation (DS4, DS5) | implemented, **needs testing** |
| USB→BT output (rumble, lightbar, triggers passthrough) + CRC | implemented, **needs testing** |
| Feature report forwarding (calibration, MAC, firmware) | implemented, **needs testing** |
| Adaptive trigger pinning (`rigid`, `weapon`, `raw`) | implemented, effect IDs **unverified** |
| PipeWire virtual sink/source | implemented |
| **Speaker / haptics / mic over BT** | **NOT implemented** – needs reverse-engineered framing (see `docs/PROTOCOL_NOTES.md`) |
| Duplicate-device handling with Steam Input | open problem |

## Quick start (Steam Deck, Desktop Mode)
```bash
./build_appimage.sh                                   # needs network
./ds-bridge-x86_64.AppImage install-perms             # once (sudo, writes /etc/udev/rules.d)
./ds-bridge-x86_64.AppImage capture-descriptor        # once per model, pad connected by USB cable
./ds-bridge-x86_64.AppImage install-service           # user systemd service, also active in Gaming Mode
journalctl --user -u ds-bridge -f
./ds-bridge-x86_64.AppImage trigger --side right --effect rigid --start 3 --force 200
```
Then pair the pad over Bluetooth and disable Steam Input for the game.

## Files
- `ds_bridge.py` – daemon + CLI (Python 3 stdlib only)
- `99-ds-bridge.rules`, `install_perms.sh` – permissions for `/dev/uhid` and `hidraw*`
- `build_appimage.sh` – builds the AppImage (optional `PY_STANDALONE_URL` to bundle Python)
- `docs/PROTOCOL_NOTES.md` – report layouts, known unknowns, how to capture traffic

## Contributing
See `CONTRIBUTING.md`. Most wanted: hardware test reports, BT audio/haptics framing, trigger effect verification.

## License
MIT (see `LICENSE`).
