from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import ctypes
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterator

from .errors import ValidationError


IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


@dataclass(frozen=True)
class ErpLaunch:
    process: subprocess.Popen[bytes]
    log_path: Path


def _tail_text(path: Path, *, max_bytes: int = 12000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


_INHERITED_PYTHON_ENV_KEYS = {
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONEXECUTABLE",
    "__PYVENV_LAUNCHER__",
    "VIRTUAL_ENV",
}

_INHERITED_TCL_ENV_KEYS = {
    "TCL_LIBRARY",
    "TK_LIBRARY",
    "TCLLIBPATH",
}


def _normalise_path_text(value: str) -> str:
    return os.path.normcase(os.path.abspath(value)).rstrip("\\/")


def _is_pyinstaller_path(value: str, meipass: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip().strip('"')
    if not cleaned:
        return False
    normalised = _normalise_path_text(cleaned)
    if meipass:
        frozen_root = _normalise_path_text(meipass)
        if normalised == frozen_root or normalised.startswith(frozen_root + os.sep):
            return True
    return "_mei" in normalised.casefold()


def build_clean_erp_environment(runtime_python: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return an environment isolated from the PyInstaller launcher runtime.

    PyInstaller may expose its temporary Tcl/Tk tree and DLL directory to child
    processes. A separately installed Python can then combine its own ``_tkinter``
    binary with the launcher's Tcl files, producing an exact-version conflict.
    The ERP must inherit a shell-like environment instead.
    """
    environment = os.environ.copy()
    removed: list[str] = []

    for key in sorted(_INHERITED_PYTHON_ENV_KEYS | _INHERITED_TCL_ENV_KEYS):
        if key in environment:
            environment.pop(key, None)
            removed.append(key)

    for key in tuple(environment):
        if key.casefold().startswith("_pyi_") or key.casefold() == "_meipass2":
            environment.pop(key, None)
            removed.append(key)

    meipass_value = str(getattr(sys, "_MEIPASS", "") or "") or None
    path_entries = []
    for entry in environment.get("PATH", "").split(os.pathsep):
        if _is_pyinstaller_path(entry, meipass_value):
            removed.append(f"PATH:{entry}")
            continue
        if entry:
            path_entries.append(entry)

    runtime_dir = str(runtime_python.parent)
    environment["PATH"] = os.pathsep.join(
        [runtime_dir, *[entry for entry in path_entries if entry != runtime_dir]]
    )
    environment["FUTONHUB_LAUNCHER"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    return environment, tuple(removed)


def _set_windows_dll_directory(path: str | None) -> None:
    if not IS_WINDOWS:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    setter = kernel32.SetDllDirectoryW
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_int
    if not setter(path):
        raise OSError(ctypes.get_last_error(), "SetDllDirectoryW failed")


@contextmanager
def clean_external_process_dll_search() -> Iterator[None]:
    """Temporarily undo PyInstaller's DLL directory before CreateProcess.

    Windows children inherit the current process DLL search configuration. The
    PyInstaller bootloader points it at ``sys._MEIPASS``; restoring the default
    search just for ``Popen`` prevents a foreign Python/Tkinter process from
    loading launcher DLLs.
    """
    frozen_root = str(getattr(sys, "_MEIPASS", "") or "")
    should_reset = IS_WINDOWS and bool(getattr(sys, "frozen", False))
    if should_reset:
        _set_windows_dll_directory(None)
    try:
        yield
    finally:
        if should_reset:
            _set_windows_dll_directory(frozen_root or None)


def launch_erp(app_dir: Path, logs_dir: Path) -> ErpLaunch:
    """Launch the ERP without routing the GUI through cmd.exe.

    ``Abrir ERP.bat`` remains the official manual entrypoint and is validated here,
    but the launcher executes the exact underlying Python command directly. This
    avoids Windows command-shell quoting and network-path errors while preserving
    the same working directory and managed runtime.
    """
    entrypoint = app_dir / "Abrir ERP.bat"
    if not entrypoint.is_file():
        raise ValidationError("Falta Abrir ERP.bat")
    if not IS_WINDOWS:
        raise ValidationError("FutonHUB ERP se ejecuta en Windows")

    runtime_file = app_dir / "runtime_python.txt"
    if not runtime_file.is_file():
        raise ValidationError("Falta runtime_python.txt")
    try:
        runtime_python = Path(runtime_file.read_text(encoding="utf-8").strip())
    except OSError as exc:
        raise ValidationError(f"No se pudo leer runtime_python.txt: {exc}") from exc
    if not runtime_python.is_file():
        raise ValidationError(
            "El entorno Python del ERP no existe. Pulsa Comprobar ahora para repararlo."
        )

    gestorwoo_dir = app_dir / "GestorWoo"
    gestorwoo_script = gestorwoo_dir / "gestorwoo.py"
    if not gestorwoo_script.is_file():
        raise ValidationError("Falta GestorWoo\\gestorwoo.py")

    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = logs_dir / f"erp-{timestamp}.log"
    environment, removed_environment = build_clean_erp_environment(runtime_python)

    command = [str(runtime_python), str(gestorwoo_script), "erp-prototype"]
    try:
        with log_path.open("ab", buffering=0) as output:
            output.write(
                (
                    f"FutonHUB ERP launch {timestamp}\r\n"
                    f"Manual entrypoint: {entrypoint}\r\n"
                    f"Runtime: {runtime_python}\r\n"
                    f"Command: {runtime_python} {gestorwoo_script} erp-prototype\r\n\r\n"
                ).encode("utf-8")
            )
            if removed_environment:
                output.write(
                    (
                        "Entorno heredado limpiado: "
                        + ", ".join(removed_environment)
                        + "\r\n"
                    ).encode("utf-8")
                )
            output.write(b"Busqueda DLL externa restaurada antes del arranque.\r\n\r\n")
            with clean_external_process_dll_search():
                process = subprocess.Popen(
                    command,
                    cwd=str(gestorwoo_dir),
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW,
                )
    except OSError as exc:
        raise ValidationError(f"No se pudo abrir FutonHUB: {exc}") from exc
    return ErpLaunch(process, log_path)


def read_erp_log_tail(path: Path) -> str:
    return _tail_text(path)


def create_desktop_shortcut(executable: Path) -> None:
    # Compatibility alias kept for earlier callers.
    create_shortcuts(executable)

UNINSTALL_REGISTRY_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FutonHUB"
)


def create_shortcuts(executable: Path) -> None:
    """Create Desktop and Start Menu shortcuts for the installed launcher."""
    if not IS_WINDOWS:
        return
    safe_executable = str(executable).replace("'", "''")
    safe_working = str(executable.parent).replace("'", "''")
    script = (
        "$w=New-Object -ComObject WScript.Shell;"
        "$targets=@("
        "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'FutonHUB.lnk'),"
        "(Join-Path ([Environment]::GetFolderPath('Programs')) 'FutonHUB.lnk')"
        ");"
        "foreach($shortcut in $targets){"
        "$s=$w.CreateShortcut($shortcut);"
        "$s.TargetPath='" + safe_executable + "';"
        "$s.WorkingDirectory='" + safe_working + "';"
        "$s.IconLocation='" + safe_executable + ",0';"
        "$s.Description='Instalar, actualizar y abrir FutonHUB';"
        "$s.Save()}"
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ],
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def register_uninstall_entry(executable: Path, version: str) -> None:
    """Register FutonHUB under Windows Settings > Installed apps for this user."""
    if not IS_WINDOWS:
        return
    try:
        import winreg
    except ImportError:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY_KEY) as key:
        values = {
            "DisplayName": "FutonHUB",
            "DisplayVersion": version,
            "Publisher": "Futon Espai",
            "InstallLocation": str(executable.parent.parent),
            "DisplayIcon": f'"{executable}",0',
            "UninstallString": f'"{executable}" --uninstall',
            "QuietUninstallString": f'"{executable}" --uninstall',
            "URLInfoAbout": "https://github.com/Shirobe95/FutonEspaiHUB",
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, 0)


def register_windows_integration(executable: Path, version: str) -> None:
    create_shortcuts(executable)
    register_uninstall_entry(executable, version)
