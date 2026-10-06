"""Bloqueos entre procesos: instancia única del launcher y exclusión de actualizaciones."""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from .errors import AlreadyRunningError

if os.name == "nt":  # pragma: no cover - ruta Windows
    import msvcrt
else:
    import fcntl


class FileLock:
    """Bloqueo exclusivo no bloqueante sobre un archivo (se libera solo si el proceso muere)."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        self.message = message
        self._handle: IO[bytes] | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise AlreadyRunningError(self.message)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":  # pragma: no cover
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise AlreadyRunningError(self.message) from exc
        self._handle = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()).encode("ascii"))
            handle.flush()
        except OSError:
            pass

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":  # pragma: no cover
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def instance_lock(state_dir: Path) -> FileLock:
    return FileLock(
        state_dir / "launcher.instance.lock",
        "FutonHUB Launcher ya está abierto en este equipo (si no ves la ventana, el ERP está en\nejecución: ciérralo y el launcher volverá a mostrarse).",
    )


def update_lock(state_dir: Path) -> FileLock:
    return FileLock(
        state_dir / "update.lock",
        "Otra instancia del launcher está actualizando FutonHUB en este momento.",
    )
