#!/usr/bin/env python3
"""
Prueba de variantes del output report 0x05 del DualShock 4 POR USB para averiguar
cuál hace sonar el ALTAVOZ integrado (el jack ya suena con el audio USB normal).

Uso (mando por cable USB, bridge parado, SIN audifonos en el jack):
    sudo setfacl -m u:$USER:rw /dev/hidrawN      # el script te dice N si falla
    python3 tools/speaker_probe.py

Reproduce un tono continuo hacia el mando y va enviando una variante distinta cada 6 s.
Anota en cuál variante empieza a sonar el altavoz. Experimental: los bytes son hipotesis.
"""
import glob
import math
import os
import re
import struct
import subprocess
import sys
import threading
import time
import wave

TONE = "/tmp/ds4_probe.wav"


def find_usb_ds4():
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            txt = open(h + "/device/uevent").read()
            m = re.search(r"HID_ID=([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", txt)
            bus, vid, pid = (int(x, 16) for x in m.groups())
        except Exception:
            continue
        if bus == 3 and vid == 0x054C and pid in (0x05C4, 0x09CC):
            return "/dev/" + os.path.basename(h)
    return None


def sink_name():
    out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "Sony" in line:
            return line.split("\t")[1]
    return None


def make_tone():
    with wave.open(TONE, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(32000)
        frames = bytearray()
        for i in range(32000 * 3):
            v = int(13000 * math.sin(2 * math.pi * 600 * i / 32000))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


def report(flags, b2, vl, vr, vs, vm=0, b23=0):
    r = bytearray(32)
    r[0] = 0x05
    r[1] = flags
    r[2] = b2
    r[8] = 0xFF            # barra de luz azul, para ver que el mando recibe el report
    r[19], r[20], r[21], r[22], r[23] = vl, vr, vm, vs, b23
    return bytes(r)


VARIANTS = [
    ("1: flags 0xFF, byte2 0x04, volumenes 0x4F", report(0xFF, 0x04, 0x4F, 0x4F, 0x4F)),
    ("2: como 1 + byte21=0x49 y byte23=0x85", report(0xFF, 0x04, 0x4F, 0x4F, 0x4F, 0x49, 0x85)),
    ("3: flags 0xF7, byte2 0x04", report(0xF7, 0x04, 0x4F, 0x4F, 0x4F)),
    ("4: flags 0xFF, byte2 0x00", report(0xFF, 0x00, 0x4F, 0x4F, 0x4F)),
    ("5: flags 0xFF, byte2 0x04, volumenes 0xFF", report(0xFF, 0x04, 0xFF, 0xFF, 0xFF)),
    ("6: solo altavoz 0x4F (L/R en 0)", report(0xFF, 0x04, 0x00, 0x00, 0x4F)),
    ("7: flags 0x80 (solo volumen altavoz?)", report(0x80, 0x04, 0x00, 0x00, 0x4F)),
    ("8: flags 0xFF, byte2 0x04, volumenes 0x20", report(0xFF, 0x04, 0x20, 0x20, 0x20)),
]


def main():
    dev = find_usb_ds4()
    if not dev:
        print("No encuentro un DS4 por USB. Conectalo con cable y repite.")
        return 1
    sink = sink_name()
    if not sink:
        print("No encuentro la salida de audio Sony en pactl.")
        return 1
    try:
        fd = os.open(dev, os.O_RDWR)
    except PermissionError:
        print(f"Sin permiso. Ejecuta:  sudo setfacl -m u:$USER:rw {dev}")
        return 1
    make_tone()
    print(f"Mando: {dev}   Salida de audio: {sink}")
    print("Quita los audifonos del jack y acerca el mando al oido.\n")
    stop = {"v": False}

    def loop():
        while not stop["v"]:
            subprocess.run(["paplay", "-d", sink, TONE])

    threading.Thread(target=loop, daemon=True).start()
    time.sleep(2)
    for name, rep in VARIANTS:
        print(">>> Variante", name, flush=True)
        os.write(fd, rep)
        time.sleep(6)
    stop["v"] = True
    print("\nFin. Dime en que variante empezo a sonar el altavoz (o si en ninguna).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
