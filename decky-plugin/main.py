import asyncio
import glob
import json
import os
import pwd
import re
import shutil
import socket
import subprocess

import decky

RULES_DST = "/etc/udev/rules.d/99-ds-bridge.rules"
PY = "/usr/bin/python3"
SONY = 0x054C
DEFAULTS = {"auto": True, "selected": "", "enabled": [], "manual": []}


def _clean_env():
    # Decky va empaquetado: su LD_LIBRARY_PATH puede romper binarios del sistema.
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    return env


def _hid_nodes():
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            txt = open(h + "/device/uevent").read()
            m = re.search(r"HID_ID=([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", txt)
            bus, vid, pid = (int(x, 16) for x in m.groups())
        except Exception:
            continue
        yield "/dev/" + os.path.basename(h), bus, vid, pid


class Plugin:
    proc = None

    # ---- utilidades
    def _user(self):
        pw = pwd.getpwnam(decky.DECKY_USER)
        return pw.pw_name, pw.pw_uid, pw.pw_dir

    def _script(self):
        return os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "ds_bridge.py")

    def _as_user(self, *args):
        name, uid, home = self._user()
        return ["runuser", "-u", name, "--", "env", f"HOME={home}",
                f"XDG_RUNTIME_DIR=/run/user/{uid}", PY, self._script(), *args]

    def _settings_path(self):
        return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

    def _settings(self):
        try:
            data = json.load(open(self._settings_path()))
        except Exception:
            data = {}
        return {**DEFAULTS, **data}

    def _save(self, s):
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
        json.dump(s, open(self._settings_path(), "w"))

    def _catalog(self):
        try:
            base = json.load(open(os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "games.json")))
        except Exception:
            base = []
        s = self._settings()
        items = [{"name": g["name"], "note": g.get("note", ""), "manual": False} for g in base]
        items += [{"name": n, "note": "Agregado a mano", "manual": True} for n in s["manual"]]
        for it in items:
            it["enabled"] = it["name"] in s["enabled"]
        return items

    # ---- ciclo de vida
    async def _unload(self):
        await self._stop_all()

    def _running(self):
        return self.proc is not None and self.proc.poll() is None

    async def _start(self):
        if self._running():
            return
        os.makedirs(decky.DECKY_PLUGIN_LOG_DIR, exist_ok=True)
        log = open(os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "daemon.log"), "ab")
        self.proc = subprocess.Popen(self._as_user("run"), stdout=log, stderr=log, env=_clean_env())
        decky.logger.info("ds-bridge iniciado (pid %s)", self.proc.pid)

    async def _hide_real(self):
        # Espera al mando virtual (USB) y le quita el acceso al hidraw real (Bluetooth):
        # el daemon ya lo tiene abierto, y el juego solo debe ver el virtual.
        for _ in range(20):
            nodes = list(_hid_nodes())
            if any(b == 3 and v == SONY for _n, b, v, _p in nodes):
                for dev, bus, vid, _pid in nodes:
                    if bus == 5 and vid == SONY:
                        subprocess.run(["setfacl", "-b", dev], env=_clean_env())
                return
            await asyncio.sleep(0.5)

    def _restore_real(self):
        # Reaplica las reglas udev (uaccess) para devolverle el mando real a Steam.
        subprocess.run(["udevadm", "trigger", "--subsystem-match=hidraw", "--action=change"],
                       env=_clean_env())

    async def _stop_all(self):
        if self._running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self._restore_real()

    # ---- API para el frontend
    async def get_state(self):
        _n, uid, home = self._user()
        pads = []
        try:
            sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sk.settimeout(1)
            sk.connect(f"/run/user/{uid}/ds-bridge.sock")
            sk.sendall(json.dumps({"cmd": "status"}).encode())
            pads = json.loads(sk.recv(65536).decode()).get("pads", [])
            sk.close()
        except Exception:
            pass
        s = self._settings()
        games = self._catalog()
        if not s["selected"] and games:
            s["selected"] = games[0]["name"]
        conf = os.path.join(home, ".config", "ds-bridge")
        return {
            "running": self._running(), "pads": pads, "auto": s["auto"],
            "selected": s["selected"], "games": games,
            "perms": os.path.exists(RULES_DST),
            "descriptor": os.path.exists(os.path.join(conf, "ds4.rd")),
        }

    async def set_auto(self, value: bool):
        s = self._settings(); s["auto"] = bool(value); self._save(s)
        return True

    async def select_game(self, name: str):
        s = self._settings(); s["selected"] = name; self._save(s)
        return True

    async def set_game_enabled(self, name: str, enabled: bool):
        s = self._settings()
        en = [n for n in s["enabled"] if n != name]
        if enabled:
            en.append(name)
        s["enabled"] = en; self._save(s)
        return True

    async def add_manual(self, name: str):
        name = name.strip()
        if not name:
            return False
        s = self._settings()
        if name not in s["manual"]:
            s["manual"].append(name)
        if name not in s["enabled"]:
            s["enabled"].append(name)
        s["selected"] = name
        self._save(s)
        return True

    async def game_event(self, name: str, running: bool):
        s = self._settings()
        low = (name or "").lower().strip()
        if not s["auto"] or not low:
            return False
        if not any(e and (e.lower() in low or low in e.lower()) for e in s["enabled"]):
            return False
        if running:
            await self._start()
            await self._hide_real()
        else:
            await self._stop_all()
        return True

    async def set_running(self, value: bool):
        if value:
            await self._start()
            await self._hide_real()
        else:
            await self._stop_all()
        return True

    async def install_perms(self):
        src = os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "99-ds-bridge.rules")
        shutil.copy(src, RULES_DST)
        with open("/etc/modules-load.d/ds-bridge.conf", "w") as f:
            f.write("uhid\n")
        env = _clean_env()
        for cmd in (["modprobe", "uhid"], ["udevadm", "control", "--reload-rules"],
                    ["udevadm", "trigger", "--subsystem-match=hidraw", "--subsystem-match=misc"]):
            subprocess.run(cmd, env=env)
        return True

    async def capture_descriptor(self):
        r = subprocess.run(self._as_user("capture-descriptor"), capture_output=True,
                           text=True, env=_clean_env())
        return (r.stdout + r.stderr).strip()
