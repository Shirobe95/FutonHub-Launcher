"""Punto de entrada de la interfaz.

El launcher estable conserva el diseño compacto de FutonEspai (``gui_compact``).
El launcher del canal de pruebas usa el estilo PALIKO (``gui_paliko``) para que
a simple vista se distinga de la instalación real.
"""
from __future__ import annotations

import tkinter as tk

from .channel import CHANNEL
from .config import LauncherConfig
from .credentials import WindowsCredentialStore
from .paths import AppPaths


def window_class():
    if CHANNEL.name == "stable":
        from .gui_compact import LauncherWindow

        return LauncherWindow
    from .gui_paliko import PalikoLauncherWindow

    return PalikoLauncherWindow


def run() -> None:
    paths = AppPaths.default()
    paths.ensure()
    config = LauncherConfig.load_or_create(paths.config / "launcher.json")
    root = tk.Tk()
    window_class()(root, paths, config, WindowsCredentialStore())
    root.mainloop()
