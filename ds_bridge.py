#!/usr/bin/env python3
"""
ds-bridge: puente Bluetooth -> "USB virtual" para DualShock 4 y DualSense en SteamOS.

Solo usa la librería estándar de Python 3 (sin pip), para poder vivir dentro de un AppImage.

Qué hace:
  1. Detecta mandos Sony conectados por Bluetooth (hidraw con bus 0005, vendor 054c).
  2. Crea un dispositivo UHID que se presenta como USB (bus 0003) con el descriptor
     de reporte USB real (capturado una vez con `capture-descriptor`).
  3. Traduce en vivo:
        BT input  (DS4 0x11 / DS5 0x31)  ->  USB input 0x01
        USB output (DS4 0x05 / DS5 0x02) ->  BT output (0x11 / 0x31 + CRC32)
        GET/SET feature report USB       ->  feature report BT equivalente
  4. Permite "anclar" efectos de gatillo adaptativo (DualSense) por socket de control.
  5. Crea sumideros PipeWire/Pulse virtuales ("Wireless Controller") y captura su audio
     para entregarlo a un backend de audio BT (ver BtAudioBackend: ES UN STUB, ver notas).
"""
import argparse
import fcntl
import glob
import json
import logging
import os
import re
import selectors
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

log = logging.getLogger("ds-bridge")

# ----------------------------------------------------------------------------- constantes
SONY = 0x054C
DS4_PIDS = {0x05C4, 0x09CC}
DS5_PIDS = {0x0CE6, 0x0DF2}  # DualSense, DualSense Edge
ALL_PIDS = DS4_PIDS | DS5_PIDS

CONF_DIR = os.path.expanduser("~/.config/ds-bridge")
SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "ds-bridge.sock")

# UHID
UHID_DESTROY, UHID_START, UHID_STOP, UHID_OPEN, UHID_CLOSE = 1, 2, 3, 4, 5
UHID_OUTPUT, UHID_GET_REPORT, UHID_GET_REPORT_REPLY = 6, 9, 10
UHID_CREATE2, UHID_INPUT2, UHID_SET_REPORT, UHID_SET_REPORT_REPLY = 11, 12, 13, 14
UHID_DATA_MAX = 4096
EVENT_SIZE = 4 + 128 + 64 + 64 + 2 + 2 + 4 * 4 + UHID_DATA_MAX  # sizeof(struct uhid_event)
BUS_USB = 3


def _ioc(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr


def HIDIOCSFEATURE(n): return _ioc(3, "H", 0x06, n)
def HIDIOCGFEATURE(n): return _ioc(3, "H", 0x07, n)


# Longitud de feature reports (kind, id_BT)
FEATURE_LEN = {
    ("ds4", 0x05): 41, ("ds4", 0x09): 16, ("ds4", 0xA3): 49,
    ("ds5", 0x05): 41, ("ds5", 0x09): 20, ("ds5", 0x20): 64,
}

# Offsets de gatillos dentro del output report USB 0x02 del DualSense (byte 0 = report id)
TRIG_OFFSETS = {"right": (11, 0x04), "left": (22, 0x08)}  # (offset, bit en valid_flag0)


# ----------------------------------------------------------------------------- descubrimiento
def hid_nodes():
    """Itera (ruta_dev, bus, vid, pid) de todos los hidraw."""
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            txt = open(h + "/device/uevent").read()
            m = re.search(r"HID_ID=([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", txt)
            bus, vid, pid = (int(x, 16) for x in m.groups())
        except (OSError, AttributeError):
            continue
        yield "/dev/" + os.path.basename(h), h, bus, vid, pid


def kind_of(pid):
    return "ds5" if pid in DS5_PIDS else "ds4"


def capture_descriptor():
    """Guarda el descriptor USB real. Requiere el mando conectado POR CABLE USB una vez."""
    os.makedirs(CONF_DIR, exist_ok=True)
    found = 0
    for dev, sysp, bus, vid, pid in hid_nodes():
        if bus == BUS_USB and vid == SONY and pid in ALL_PIDS:
            rd = open(sysp + "/device/report_descriptor", "rb").read()
            out = os.path.join(CONF_DIR, kind_of(pid) + ".rd")
            open(out, "wb").write(rd)
            print(f"[ok] {dev} {vid:04x}:{pid:04x} -> {out} ({len(rd)} bytes)")
            found += 1
    if not found:
        print("No se encontró ningún mando Sony por USB. Conéctalo con cable y repite.")
        return 1
    return 0


def load_descriptor(kind):
    p = os.path.join(CONF_DIR, kind + ".rd")
    return open(p, "rb").read() if os.path.exists(p) else None


# ----------------------------------------------------------------------------- mando
class Pad:
    def __init__(self, path, pid, rd):
        self.path, self.pid, self.kind = path, pid, kind_of(pid)
        self.hid = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        self.uhid = os.open("/dev/uhid", os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        self.seq = 0
        self.last_usb_out = None
        self.trig = {}  # side -> 11 bytes anclados
        # Leer el feature report de calibración hace que el mando pase de los reports
        # "simplificados" (0x01) a los completos (DS4: 0x11, DS5: 0x31) por Bluetooth.
        self.get_feature(0x02 if self.kind == "ds4" else 0x05)
        self._create(rd)

    # --- UHID helpers
    def _uhid_write(self, etype, payload=b""):
        os.write(self.uhid, (struct.pack("<I", etype) + payload).ljust(EVENT_SIZE, b"\0"))

    def _create(self, rd):
        name = b"Wireless Controller" if self.kind == "ds4" else b"DualSense Wireless Controller"
        uniq = f"dsbridge-{os.path.basename(self.path)}".encode()
        payload = struct.pack("<128s64s64sHHIIII", name, b"ds-bridge/virtual", uniq,
                              len(rd), BUS_USB, SONY, self.pid, 0x0100, 0) + rd
        self._uhid_write(UHID_CREATE2, payload)
        log.info("UHID creado para %s (%s, pid %04x)", self.path, self.kind, self.pid)

    def close(self):
        for fn in (lambda: self._uhid_write(UHID_DESTROY),):
            try: fn()
            except OSError: pass
        for fd in (self.hid, self.uhid):
            try: os.close(fd)
            except OSError: pass

    # --- feature reports (USB -> BT)
    def get_feature(self, rnum):
        src = rnum
        if self.kind == "ds4":
            src = {0x02: 0x05, 0x12: 0x09, 0x81: 0x09}.get(rnum, rnum)
        n = FEATURE_LEN.get((self.kind, src), 64)
        buf = bytearray(n)
        buf[0] = src
        try:
            got = fcntl.ioctl(self.hid, HIDIOCGFEATURE(n), buf)
        except OSError as e:
            log.debug("GFEATURE 0x%02x falló: %s", src, e)
            return 5, b""  # EIO
        rep = bytearray(buf[:got])
        rep[0] = rnum
        if self.kind == "ds4" and rnum in (0x12, 0x81) and len(rep) > 1: rep[1] ^= 0x01  # MAC distinta: hid-playstation rechaza MAC duplicada
        if self.kind == "ds4" and rnum == 0x02:
            rep = rep[:37]  # tamaño USB
        return 0, bytes(rep)

    def set_feature(self, rnum, data):
        try:
            fcntl.ioctl(self.hid, HIDIOCSFEATURE(len(data)), bytearray(data))
            return 0
        except OSError:
            return 5

    # --- eventos del UHID (lo que hace el kernel/juego con el dispositivo virtual)
    def on_uhid(self):
        try:
            ev = os.read(self.uhid, EVENT_SIZE)
        except BlockingIOError:
            return
        et = struct.unpack_from("<I", ev)[0]
        if et == UHID_GET_REPORT:
            rid, rnum, _rtype = struct.unpack_from("<IBB", ev, 4)
            err, rep = self.get_feature(rnum)
            self._uhid_write(UHID_GET_REPORT_REPLY, struct.pack("<IHH", rid, err, len(rep)) + rep)
        elif et == UHID_SET_REPORT:
            rid, rnum, _rtype, size = struct.unpack_from("<IBBH", ev, 4)
            err = self.set_feature(rnum, ev[12:12 + size])
            self._uhid_write(UHID_SET_REPORT_REPLY, struct.pack("<IH", rid, err))
        elif et == UHID_OUTPUT:
            size = struct.unpack_from("<H", ev, 4 + UHID_DATA_MAX)[0]
            self.on_output(ev[4:4 + size])
        elif et in (UHID_START, UHID_STOP, UHID_OPEN, UHID_CLOSE):
            log.debug("uhid evento %d", et)

    # --- input BT -> USB
    def on_hid(self):
        try:
            d = os.read(self.hid, 128)
        except BlockingIOError:
            return
        usb = None
        if self.kind == "ds4" and d[:1] == b"\x11" and len(d) >= 66:
            usb = b"\x01" + d[3:66]
        elif self.kind == "ds5" and d[:1] == b"\x31" and len(d) >= 65:
            usb = b"\x01" + d[2:65]
        if usb:
            self._uhid_write(UHID_INPUT2, struct.pack("<H", len(usb)) + usb)

    # --- output USB -> BT
    @staticmethod
    def _crc(bt):
        c = zlib.crc32(bytes(bt[:74]), zlib.crc32(b"\xa2")) & 0xFFFFFFFF
        struct.pack_into("<I", bt, 74, c)
        return bytes(bt)

    def _ds5_to_bt(self, usb):
        bt = bytearray(78)
        bt[0] = 0x31
        bt[1] = (self.seq & 0x0F) << 4
        self.seq += 1
        bt[2] = 0x10                      # tag de output report DualSense
        bt[3:3 + 62] = usb[1:63]          # bloque "common" idéntico al USB
        return self._crc(bt)

    def _ds4_to_bt(self, usb):
        bt = bytearray(78)
        bt[0] = 0x11
        bt[1] = 0xC0                      # HID + CRC, poll rate 0
        bt[2] = 0x00                      # audio control
        bt[3:3 + 31] = usb[1:32]
        return self._crc(bt)

    def _apply_triggers(self, usb):
        for side, (off, flag) in TRIG_OFFSETS.items():
            if side in self.trig:
                usb[off:off + 11] = self.trig[side].ljust(11, b"\0")[:11]
                usb[1] |= flag

    def _send_hid(self, data):
        try:
            os.write(self.hid, data)
        except BlockingIOError:
            pass

    def on_output(self, rep):
        if self.kind == "ds5" and rep[:1] == b"\x02":
            usb = bytearray(rep.ljust(63, b"\0")[:63])
            self._apply_triggers(usb)
            self.last_usb_out = bytes(usb)
            self._send_hid(self._ds5_to_bt(usb))
        elif self.kind == "ds4" and rep[:1] == b"\x05":
            usb = bytearray(rep.ljust(32, b"\0")[:32])
            self._send_hid(self._ds4_to_bt(usb))

    def raw_bt_output(self, body):
        """Inyecta un output report BT crudo (sin CRC). body[0] = report id (0x31/0x11/...)."""
        bt = bytearray(78)
        bt[:len(body)] = body[:74]
        self._send_hid(self._crc(bt))

    def set_trigger(self, side, payload):
        """payload = 11 bytes: [modo, p1..p10]. Se ancla y se envía de inmediato."""
        if self.kind != "ds5":
            return False
        self.trig[side] = payload
        usb = bytearray(self.last_usb_out or bytes(63))
        usb[0] = 0x02
        if not self.last_usb_out:
            usb[1] = 0
        self._apply_triggers(usb)
        self.last_usb_out = bytes(usb)
        self._send_hid(self._ds5_to_bt(usb))
        return True


# ----------------------------------------------------------------------------- audio
class BtAudioBackend:
    """
    STUB. Aquí va el codificador/empaquetador de audio hacia el mando por BT.

    NO está implementado a propósito: ni el altavoz del DS4 ni el audio/háptica del
    DualSense usan un perfil de audio Bluetooth estándar (A2DP/HFP); viajan dentro de
    output reports HID propietarios con framing + códec concretos que no están
    documentados oficialmente. Debes capturar ese tráfico (p. ej. `btmon` mientras
    Sony Remote Play / un driver de Windows reproduce sonido en el mando) y rellenar
    play() con el formato real. Ver notas en la respuesta.
    """
    def __init__(self, pads):
        self.pads = pads
        self._warned = False

    def play(self, pcm_s16le_stereo_48k: bytes):
        if not self._warned:
            log.warning("BtAudioBackend.play(): no implementado, descartando audio.")
            self._warned = True

    def mic_read(self):
        return b""


class AudioRouter:
    SINK = "ds_bridge_speaker"
    MIC_SINK = "ds_bridge_mic_sink"
    MIC_SRC = "ds_bridge_mic"

    def __init__(self, backend):
        self.backend, self.modules, self.proc, self.run = backend, [], None, False

    def _pactl(self, *a):
        r = subprocess.run(["pactl", *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def start(self):
        if not shutil.which("pactl") or not shutil.which("parec"):
            log.warning("pactl/parec no disponibles: audio deshabilitado")
            return
        for args in (
            ["load-module", "module-null-sink", f"sink_name={self.SINK}",
             'sink_properties=device.description="Wireless Controller"'],
            ["load-module", "module-null-sink", f"sink_name={self.MIC_SINK}",
             'sink_properties=device.description="Wireless Controller Mic (interno)"'],
            ["load-module", "module-remap-source", f"master={self.MIC_SINK}.monitor",
             f"source_name={self.MIC_SRC}",
             'source_properties=device.description="Wireless Controller Mic"'],
        ):
            mid = self._pactl(*args)
            if mid:
                self.modules.append(mid)
        self.run = True
        threading.Thread(target=self._capture, daemon=True).start()

    def _capture(self):
        cmd = ["parec", "-d", f"{self.SINK}.monitor", "--format=s16le",
               "--rate=48000", "--channels=2", "--latency-msec=20"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        chunk = 48000 * 4 // 50  # 20 ms
        while self.run:
            pcm = self.proc.stdout.read(chunk)
            if not pcm:
                break
            self.backend.play(pcm)

    def stop(self):
        self.run = False
        if self.proc:
            self.proc.terminate()
        for mid in reversed(self.modules):
            self._pactl("unload-module", mid)


# ----------------------------------------------------------------------------- daemon
def effect_bytes(c):
    e = c.get("effect")
    if e == "off":
        return bytes([0x05])
    if e == "rigid":      # resistencia rígida desde la posición `start` con fuerza `force`
        return bytes([0x01, c.get("start", 0) & 0xFF, c.get("force", 255) & 0xFF])
    if e == "weapon":     # "click" de arma entre zonas start..end (2..8), fuerza 0..8
        s, en, st = c.get("start", 2), c.get("end", 5), c.get("strength", 6)
        mask = (1 << s) | (1 << en)
        return bytes([0x25, mask & 0xFF, mask >> 8, max(0, st - 1) & 0xFF])
    if e == "raw":
        return bytes.fromhex(c["hex"])
    raise ValueError("efecto desconocido")


def handle_ctl(cmd, pads):
    c = cmd.get("cmd")
    if c == "status":
        return {"pads": [{"path": p.path, "kind": p.kind, "pinned": list(p.trig)} for p in pads.values()]}
    if c == "trigger":
        pl = effect_bytes(cmd)
        n = sum(p.set_trigger(cmd["side"], pl) for p in pads.values())
        return {"ok": True, "applied": n}
    if c == "clear":
        for p in pads.values():
            p.trig.clear()
        return {"ok": True}
    if c == "raw_output":
        for p in pads.values():
            p.raw_bt_output(bytes.fromhex(cmd["hex"]))
        return {"ok": True}
    return {"error": "cmd desconocido"}


def run_daemon():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.access("/dev/uhid", os.R_OK | os.W_OK):
        log.error("Sin permisos en /dev/uhid. Ejecuta install_perms.sh (ver README).")
        return 1
    sel, pads, warned = selectors.DefaultSelector(), {}, set()
    backend = BtAudioBackend(pads)
    audio = AudioRouter(backend)
    audio.start()

    try: os.unlink(SOCK_PATH)
    except OSError: pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH); srv.listen(4); srv.setblocking(False)
    sel.register(srv, selectors.EVENT_READ, ("ctl", None))

    stop = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(v=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(v=True))

    def drop(p):
        for fd in (p.hid, p.uhid):
            try: sel.unregister(fd)
            except (KeyError, ValueError): pass
        pads.pop(p.path, None)
        p.close()
        log.info("Mando %s desconectado", p.path)

    last_scan = 0.0
    while not stop["v"]:
        if time.time() - last_scan > 2:
            last_scan = time.time()
            present = set()
            for dev, _s, bus, vid, pid in hid_nodes():
                if bus == 5 and vid == SONY and pid in ALL_PIDS:   # solo Bluetooth
                    present.add(dev)
                    if dev in pads:
                        continue
                    rd = load_descriptor(kind_of(pid))
                    if rd is None:
                        if dev not in warned:
                            log.error("Falta ~/.config/ds-bridge/%s.rd -> ejecuta `capture-descriptor` "
                                      "con el mando por USB una vez.", kind_of(pid))
                            warned.add(dev)
                        continue
                    try:
                        p = Pad(dev, pid, rd)
                    except OSError as e:
                        log.error("No se pudo abrir %s: %s", dev, e)
                        continue
                    pads[dev] = p
                    sel.register(p.hid, selectors.EVENT_READ, ("hid", p))
                    sel.register(p.uhid, selectors.EVENT_READ, ("uhid", p))
            for dev in [d for d in pads if d not in present]:
                drop(pads[dev])

        for key, _ in sel.select(timeout=1):
            kind, p = key.data
            try:
                if kind == "hid": p.on_hid()
                elif kind == "uhid": p.on_uhid()
                else:
                    conn, _a = srv.accept()
                    conn.settimeout(0.5)
                    try:
                        resp = handle_ctl(json.loads(conn.recv(8192) or b"{}"), pads)
                    except Exception as e:  # noqa
                        resp = {"error": str(e)}
                    conn.sendall(json.dumps(resp).encode()); conn.close()
            except OSError:
                if p: drop(p)

    audio.stop()
    for p in list(pads.values()):
        drop(p)
    try: os.unlink(SOCK_PATH)
    except OSError: pass
    return 0


# ----------------------------------------------------------------------------- CLI
def client(cmd):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK_PATH)
    s.sendall(json.dumps(cmd).encode())
    print(s.recv(65536).decode())


def install_service():
    exe = os.environ.get("APPIMAGE") or os.path.abspath(sys.argv[0])
    d = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(d, exist_ok=True)
    open(d + "/ds-bridge.service", "w").write(
        f"[Unit]\nDescription=DS4/DualSense Bluetooth bridge\nAfter=pipewire.service\n\n"
        f"[Service]\nExecStart={exe} run\nRestart=on-failure\nRestartSec=2\n\n"
        f"[Install]\nWantedBy=default.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "--now", "ds-bridge.service"])
    print("Servicio instalado y arrancado (también en Modo Gaming).")


def main():
    ap = argparse.ArgumentParser(prog="ds-bridge")
    sp = ap.add_subparsers(dest="c")
    sp.add_parser("run")
    sp.add_parser("capture-descriptor")
    sp.add_parser("install-service")
    sp.add_parser("status")
    sp.add_parser("clear")
    t = sp.add_parser("trigger")
    t.add_argument("--side", choices=["left", "right"], required=True)
    t.add_argument("--effect", choices=["off", "rigid", "weapon", "raw"], required=True)
    t.add_argument("--start", type=int, default=2)
    t.add_argument("--end", type=int, default=5)
    t.add_argument("--force", type=int, default=255)
    t.add_argument("--strength", type=int, default=6)
    t.add_argument("--hex", default="")
    a = ap.parse_args()
    if a.c in (None, "run"): sys.exit(run_daemon())
    if a.c == "capture-descriptor": sys.exit(capture_descriptor())
    if a.c == "install-service": return install_service()
    if a.c == "status": return client({"cmd": "status"})
    if a.c == "clear": return client({"cmd": "clear"})
    if a.c == "trigger":
        return client({"cmd": "trigger", "side": a.side, "effect": a.effect, "start": a.start,
                       "end": a.end, "force": a.force, "strength": a.strength, "hex": a.hex})


if __name__ == "__main__":
    main()
