import json
import os
import pwd
import shutil
import socket
import subprocess

import decky

RULES_DST = "/etc/udev/rules.d/99-ds-bridge.rules"
PY = "/usr/bin/python3"


def _clean_env():
    # Decky Loader va empaquetado: su LD_LIBRARY_PATH puede romper binarios del sistema.
    env = dict(os.environ)
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(k, None)
    return env


class Plugin:
    proc = None

    # ---- rutas / usuario
    def _user(self):
        pw = pwd.getpwnam(decky.DECKY_USER)
        return pw.pw_name, pw.pw_uid, pw.pw_dir

    def _script(self):
        return os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "ds_bridge.py")

    def _enabled_file(self):
        return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "enabled")

    def _as_user(self, *args):
        name, uid, home = self._user()
        return ["runuser", "-u", name, "--", "env", f"HOME={home}",
                f"XDG_RUNTIME_DIR=/run/user/{uid}", PY, self._script(), *args]

    # ---- ciclo de vida
    async def _main(self):
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
        if os.path.exists(self._enabled_file()):
            await self.start()

    async def _unload(self):
        await self.stop()

    # ---- control del daemon
    def _running(self):
        return self.proc is not None and self.proc.poll() is None

    async def start(self):
        if self._running():
            return True
        os.makedirs(decky.DECKY_PLUGIN_LOG_DIR, exist_ok=True)
        log = open(os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "daemon.log"), "ab")
        self.proc = subprocess.Popen(self._as_user("run"), stdout=log, stderr=log,
                                     env=_clean_env())
        decky.logger.info("ds-bridge daemon iniciado (pid %s)", self.proc.pid)
        return True

    async def stop(self):
        if self._running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        return True

    # ---- API para el frontend
    async def set_enabled(self, enabled: bool):
        f = self._enabled_file()
        if enabled:
            open(f, "w").close()
            await self.start()
        else:
            if os.path.exists(f):
                os.remove(f)
            await self.stop()
        return await self.get_status()

    async def get_status(self):
        _n, uid, home = self._user()
        pads = []
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(f"/run/user/{uid}/ds-bridge.sock")
            s.sendall(json.dumps({"cmd": "status"}).encode())
            pads = json.loads(s.recv(65536).decode()).get("pads", [])
            s.close()
        except Exception:
            pass
        conf = os.path.join(home, ".config", "ds-bridge")
        return {
            "running": self._running(),
            "pads": pads,
            "perms": os.path.exists(RULES_DST),
            "desc_ds4": os.path.exists(os.path.join(conf, "ds4.rd")),
            "desc_ds5": os.path.exists(os.path.join(conf, "ds5.rd")),
        }

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
