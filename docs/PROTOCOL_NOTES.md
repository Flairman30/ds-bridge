# Protocol notes

Derived from the behaviour of the Linux `hid-sony` / `hid-playstation` drivers. **Verify on hardware.**

## Input (BT → USB), conversion used
- DS4 BT `0x11` (78 B): `usb = 0x01 + bt[3:66]`  (enabled by reading feature `0x05` over BT)
- DS5 BT `0x31` (78 B): `usb = 0x01 + bt[2:65]`  (enabled by reading feature `0x05`)

## Output (USB → BT)
- DS4: USB `0x05` (32 B) → BT `0x11` (78 B): `[0x11, 0xC0, 0x00, usb[1:32]..., crc32 @74]`
- DS5: USB `0x02` (63 B) → BT `0x31` (78 B): `[0x31, seq<<4, 0x10, usb[1:63]..., crc32 @74]`
- CRC32 (little-endian at bytes 74..77) over `0xA2` + `bt[0:74]`
- DS5 USB output offsets: `valid_flag0`=1, right trigger block=11..21 (flag bit 0x04), left trigger block=22..32 (flag bit 0x08)

## Feature reports
DS4 USB→BT id mapping used: `0x02→0x05` (calibration), `0x81→0x09` (MAC). DS5: same ids on both buses.

## Unknown / needs capture
- DS4 speaker audio over BT (report ids, frame sizes, codec)
- DS5 audio/haptics over BT (report `0x32`-style packets? framing and codec unverified)
- Microphone return path over BT
- Trigger effect modes beyond `0x01` (rigid) and `0x25` (weapon): unverified here

## Capturing traffic
`sudo btmon -w capture.btsnoop` while a known-good host drives the feature, then open in Wireshark.

## DS4 Bluetooth audio — community findings (UNVERIFIED on our hardware)
Collected from public write-ups (ds4drv audio issue threads, a 2021 Linux gist `play.py`, DS4-Sound-Link (MIT),
PadForge reference list, DS4Windows release notes). Described in our own words; no third-party code copied.
Verify everything with `btmon` before relying on it.

- Audio is **not** A2DP/HFP. It rides inside vendor HID output reports, encoded with **SBC**.
- Report ids reported in use: `0x11` (controls: LED/rumble + volumes, "arming"), `0x14`, `0x15`, `0x17` (audio; `0x19` also mentioned).
- Reported SBC parameters: **32 kHz**, stereo, **dual channel**, **16 blocks, 8 subbands, bitpool 25**
  -> 112-byte frames (4 ms each). Cross-check: 224 B = 2 frames, 448 B = 4 frames = 16 ms.
  (DS4Windows Nexus notes mention a 16 kHz SBC route for the physical DS4, and one thread reports less stutter at 16 kHz:
  rate is a point to settle by capture.)
- Reported framing (per the 2021 gist): header bytes `[id, 0x40|0xC0, 0xA0]`, 16-bit little-endian frame counter
  (increment 2 for 0x14/0x15, 4 for 0x17), one fixed header byte (`0x24`), then SBC payload (224 B for 0x14/0x15, 448 B for 0x17),
  zero padding, and for 0x17 a trailing CRC. 0x15 additionally embeds the same controls block as 0x11.
- A mix of 0x14/0x15 (small) and periodic 0x17 (large) was used in that script.
- A CRC32 is reportedly required for the controller to accept audio reports (we use seed 0xA2 for control reports; confirm for audio).
- Routing speaker vs headphone jack is reportedly a single byte in the controls block; the built-in speaker is mono.
- A mode byte of `0xA0` reportedly lets gamepad input reports keep flowing during audio.
- Reports must be paced (about 8-16 ms cadence) and the speaker needs a short priming burst; jitter causes stutter.
- DualSense is different: Opus at 48 kHz for speaker, signed 8-bit samples for haptics, combined transport. Layout not collected yet.

### Licensing note
DS4Windows Nexus is GPL; we have **not** read its source. MIT-licensed references (DS4-Sound-Link, nefarius DS4AudioStreamer,
ds4drv) are safer for an MIT project. A gist without a license should be treated as "facts only, write your own code".
