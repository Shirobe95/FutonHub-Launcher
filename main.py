from __future__ import annotations

from datetime import datetime
import json
import platform
import sys
import traceback

from futonhub_auto import LAUNCHER_VERSION
from futonhub_auto.bootstrap import ensure_launcher_installed
from futonhub_auto.channel import CHANNEL
from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import WindowsCredentialStore
from futonhub_auto.errors import AlreadyRunningError
from futonhub_auto.gui import run
from futonhub_auto.locking import instance_lock
from futonhub_auto.paths import AppPaths
from futonhub_auto.self_update import write_ok_marker
from futonhub_auto.uninstall import run_uninstall_prompt


def _show_error(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:  # noqa: BLE001 - sin entorno gráfico solo queda el log
        pass


def _log_crash(paths: AppPaths) -> str:
    text = traceback.format_exc()
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        target = paths.logs / "launcher-crash.log"
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n{text}")
        return str(target)
    except OSError:
        return "(no se pudo escribir el log)"


def selftest(target: str) -> int:
    """Prueba de humo del EXE compilado (sin tocar la instalación): lo usa el CI antes de publicar."""
    result = {"ok": False, "version": LAUNCHER_VERSION, "channel": CHANNEL.name, "python": platform.python_version()}
    try:
        import importlib

        importlib.import_module("tkinter")

        result["tk"] = True
        result["frozen"] = bool(getattr(sys, "frozen", False))
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    try:
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
    except OSError:
        return 2
    return 0 if result["ok"] else 1


def main() -> int:
    if "--selftest" in sys.argv:
        index = sys.argv.index("--selftest")
        return selftest(sys.argv[index + 1] if index + 1 < len(sys.argv) else "selftest.json")
    paths = AppPaths.default()
    paths.ensure()
    uninstalling = "--uninstall" in sys.argv[1:]
    if not uninstalling:
        try:
            # Debe ir ANTES del bloqueo: si copia el EXE y relanza, el hijo necesita el bloqueo libre.
            if ensure_launcher_installed(paths):
                return 0
        except Exception:  # noqa: BLE001
            where = _log_crash(paths)
            _show_error("FutonHUB Launcher", f"No se pudo instalar el launcher.\nDetalle: {where}")
            return 1
    lock = instance_lock(paths.state)
    try:
        lock.acquire()
    except AlreadyRunningError as exc:
        _show_error("FutonHUB Launcher", str(exc))
        return 3
    try:
        if uninstalling:
            config = LauncherConfig.load_or_create(paths.config / "launcher.json")
            confirmed = run_uninstall_prompt(
                paths,
                WindowsCredentialStore(),
                config.credential_target,
            )
            return 0 if confirmed else 1
        write_ok_marker(paths, LAUNCHER_VERSION)
        run()
        return 0
    except Exception:  # noqa: BLE001 - registro y aviso en lugar de cierre mudo
        where = _log_crash(paths)
        _show_error(
            "FutonHUB Launcher",
            f"El launcher tuvo un error inesperado.\nDetalle técnico guardado en:\n{where}",
        )
        return 1
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
