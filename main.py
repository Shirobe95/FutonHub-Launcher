from __future__ import annotations

from datetime import datetime
import sys
import traceback

from futonhub_auto.bootstrap import ensure_launcher_installed
from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import WindowsCredentialStore
from futonhub_auto.errors import AlreadyRunningError
from futonhub_auto.gui import run
from futonhub_auto.locking import instance_lock
from futonhub_auto.paths import AppPaths
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


def main() -> int:
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
