from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from .credentials import CredentialStore
from .errors import ValidationError
from .paths import AppPaths


IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def desktop_shortcut_path() -> Path:
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return desktop / "FutonHUB.lnk"


def build_cleanup_script(paths: AppPaths, *, pid: int) -> str:
    root = str(paths.root).replace("'", "''")
    return "\n".join(
        [
            "$ErrorActionPreference = 'SilentlyContinue'",
            f"$LauncherPid = {int(pid)}",
            f"$InstallRoot = '{root}'",
            "$Desktop = [Environment]::GetFolderPath('Desktop')",
            "$Programs = [Environment]::GetFolderPath('Programs')",
            "$DesktopShortcut = Join-Path $Desktop 'FutonHUB.lnk'",
            "$StartShortcut = Join-Path $Programs 'FutonHUB.lnk'",
            "$UninstallKey = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FutonHUB'",
            "Wait-Process -Id $LauncherPid -ErrorAction SilentlyContinue",
            "Start-Sleep -Milliseconds 700",
            "Remove-Item -LiteralPath $DesktopShortcut -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $StartShortcut -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue",
            "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
            "",
        ]
    )


def schedule_full_uninstall(
    paths: AppPaths,
    store: CredentialStore,
    credential_target: str,
    *,
    pid: int | None = None,
) -> Path:
    """Schedule deletion after the current launcher process exits.

    The credential is removed immediately. The application tree and desktop
    shortcut are removed by a temporary PowerShell script outside the install
    directory, because Windows cannot delete the running EXE in-place.
    """
    if not IS_WINDOWS:
        raise ValidationError("La desinstalación automática requiere Windows")
    current_pid = int(pid or os.getpid())
    store.delete(credential_target)
    temp_root = Path(tempfile.gettempdir()) / "FutonHUB-Uninstall"
    temp_root.mkdir(parents=True, exist_ok=True)
    script = temp_root / f"remove-{current_pid}.ps1"
    script.write_text(
        build_cleanup_script(paths, pid=current_pid),
        encoding="utf-8-sig",
        newline="\r\n",
    )
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
            ],
            cwd=str(temp_root),
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise ValidationError(f"No se pudo iniciar la desinstalación: {exc}") from exc
    return script


def run_uninstall_prompt(
    paths: AppPaths,
    store: CredentialStore,
    credential_target: str,
) -> bool:
    """Show a standalone confirmation when invoked from Windows Settings."""
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        if not messagebox.askyesno(
            "Desinstalar FutonHUB",
            "Se eliminarán la aplicación, el launcher, el .env, los datos locales, "
            "los logs, las copias de seguridad, el runtime y la credencial GitHub.\n\n"
            "Esta acción no se puede deshacer. ¿Continuar?",
            icon="warning",
            parent=root,
        ):
            return False
        confirmation = simpledialog.askstring(
            "Confirmación final",
            "Escribe BORRAR TODO para confirmar:",
            parent=root,
        )
        if (confirmation or "").strip().upper() != "BORRAR TODO":
            messagebox.showinfo(
                "Desinstalar FutonHUB", "Desinstalación cancelada.", parent=root
            )
            return False
        schedule_full_uninstall(paths, store, credential_target)
        messagebox.showinfo(
            "Desinstalar FutonHUB",
            "FutonHUB se cerrará y se eliminarán todos sus archivos locales.",
            parent=root,
        )
        return True
    finally:
        root.destroy()
