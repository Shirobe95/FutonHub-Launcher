from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import LAUNCHER_VERSION
from .desktop import register_windows_integration
from .paths import AppPaths


CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def launcher_install_path(paths: AppPaths) -> Path:
    return paths.root / "Launcher" / "FutonHUB Launcher.exe"


def _same_file_content(left: Path, right: Path) -> bool:
    if not left.is_file() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False

    def digest(path: Path) -> str:
        value = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(chunk)
        return value.hexdigest()

    return digest(left) == digest(right)


def ensure_launcher_installed(paths: AppPaths) -> bool:
    """Copy the frozen EXE to LocalAppData and restart from there.

    Returns True when the current process should terminate because a replacement
    process has been started.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    current = Path(sys.executable).resolve()
    target = launcher_install_path(paths).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if current == target:
        register_windows_integration(target, LAUNCHER_VERSION)
        return False

    temporary = target.with_suffix(".exe.new")
    shutil.copy2(current, temporary)
    if target.exists() and _same_file_content(temporary, target):
        temporary.unlink(missing_ok=True)
    else:
        temporary.replace(target)
    register_windows_integration(target, LAUNCHER_VERSION)
    subprocess.Popen(
        [str(target)],
        cwd=str(target.parent),
        creationflags=CREATE_NO_WINDOW,
    )
    return True
