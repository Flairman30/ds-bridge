# Contributing

Issues and PRs welcome (English or Spanish).

## Most useful contributions
1. **Test reports**: Steam Deck model, SteamOS version, pad model/firmware, `journalctl --user -u ds-bridge` output, game tested.
2. **BT audio/haptics framing**: capture with `btmon` (or Wireshark + `bluez` HCI snoop) while a known-good host plays sound on the pad.
   Document byte layouts in `docs/PROTOCOL_NOTES.md`, then implement `BtAudioBackend.play()` in `ds_bridge.py`.
3. **Adaptive trigger effects**: verify mode IDs/params on a real DualSense and extend `effect_bytes()`.
4. **Steam Input coexistence**: a clean way to avoid duplicate devices.

## Guidelines
- Python 3 stdlib only (the AppImage relies on the host `python3` unless Python is bundled).
- No Sony proprietary code/firmware/dumps. Only clean-room, observed-behaviour documentation.
- Keep `bash -n` and `python3 -m py_compile` passing. Describe how you tested.
