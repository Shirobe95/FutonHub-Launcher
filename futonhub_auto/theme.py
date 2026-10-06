"""Sistema visual PALIKO para el launcher: oscuro grafito/azulado, acentos azul-cian,
paneles discretos, tipografía limpia y jerarquía clara (sin ornamento).

Todo el aspecto vive aquí (tokens + estilos ttk) para que la lógica de ``gui.py`` no dependa
de colores concretos y el ERP pueda reutilizar los mismos tokens más adelante.
"""
from __future__ import annotations

import ctypes
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str = "#0B0F14"          # fondo de ventana (grafito azulado)
    surface: str = "#111821"     # paneles
    surface_2: str = "#16202B"   # paneles elevados / botones secundarios
    surface_3: str = "#1C2937"   # hover
    border: str = "#233041"
    border_strong: str = "#2F4258"
    text: str = "#E6EDF5"
    text_muted: str = "#8A9BB0"
    text_faint: str = "#5F7186"
    accent: str = "#22D3EE"      # cian
    accent_hover: str = "#67E8F9"
    accent_pressed: str = "#0EA5C4"
    accent_blue: str = "#3B82F6"
    on_accent: str = "#04212A"
    success: str = "#34D399"
    warning: str = "#FBBF24"
    danger: str = "#F87171"
    danger_bg: str = "#2A1519"


PALETTE = Palette()

STATE_COLORS = {
    "idle": PALETTE.text_faint,
    "working": PALETTE.accent,
    "ready": PALETTE.success,
    "warning": PALETTE.warning,
    "error": PALETTE.danger,
}


def pick_font(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    available = {name.casefold(): name for name in tkfont.families(root)}
    for name in candidates:
        if name.casefold() in available:
            return available[name.casefold()]
    return fallback


@dataclass(frozen=True)
class Fonts:
    ui: str
    mono: str

    def get(self, size: int, weight: str = "normal", mono: bool = False) -> tuple[str, int, str]:
        return (self.mono if mono else self.ui, size, weight)


def load_fonts(root: tk.Misc) -> Fonts:
    return Fonts(
        ui=pick_font(root, ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"), "TkDefaultFont"),
        mono=pick_font(root, ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"), "TkFixedFont"),
    )


def apply_dark_title_bar(root: tk.Tk) -> None:
    """Barra de título oscura en Windows 10/11 (si no se puede, se ignora)."""
    if os.name != "nt":
        return
    try:  # pragma: no cover - solo Windows
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / Win10 antiguo)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:  # noqa: BLE001
        pass


def configure_styles(root: tk.Tk, fonts: Fonts) -> None:
    p = PALETTE
    root.configure(bg=p.bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=p.bg, foreground=p.text, font=fonts.get(10), borderwidth=0, focuscolor=p.bg)

    def button(name: str, bg: str, fg: str, hover: str, pressed: str, border: str) -> None:
        style.configure(
            name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg, darkcolor=bg,
            relief="flat", padding=(14, 9), font=fonts.get(10, "bold"), focuscolor=bg, borderwidth=1,
        )
        style.map(
            name,
            background=[("disabled", p.surface), ("pressed", pressed), ("active", hover)],
            foreground=[("disabled", p.text_faint)],
            bordercolor=[("disabled", p.border), ("focus", p.accent)],
            lightcolor=[("pressed", pressed), ("active", hover)],
            darkcolor=[("pressed", pressed), ("active", hover)],
        )

    button("Primary.TButton", p.accent, p.on_accent, p.accent_hover, p.accent_pressed, p.accent)
    button("Secondary.TButton", p.surface_2, p.text, p.surface_3, p.surface, p.border_strong)
    button("Ghost.TButton", p.bg, p.text_muted, p.surface_2, p.surface, p.bg)
    style.configure("Ghost.TButton", font=fonts.get(10))
    style.configure("TMenubutton", background=p.bg, foreground=p.text_muted, bordercolor=p.bg, arrowcolor=p.text_muted, padding=(12, 9), font=fonts.get(10))
    style.map("TMenubutton", background=[("active", p.surface_2), ("disabled", p.bg)], foreground=[("disabled", p.text_faint)])
    style.configure(
        "Paliko.Horizontal.TProgressbar", troughcolor=p.surface_2, background=p.accent,
        bordercolor=p.surface_2, lightcolor=p.accent, darkcolor=p.accent, thickness=6,
    )
    style.configure("Paliko.Vertical.TScrollbar", troughcolor=p.surface, background=p.surface_3, bordercolor=p.surface, arrowcolor=p.text_muted, lightcolor=p.surface_3, darkcolor=p.surface_3, gripcount=0)
    style.map("Paliko.Vertical.TScrollbar", background=[("active", p.border_strong)])


def card(parent: tk.Misc, *, padx: int = 16, pady: int = 14, bg: str | None = None) -> tk.Frame:
    """Panel plano con borde de 1 px (sin sombras ni ornamento)."""
    frame = tk.Frame(parent, bg=bg or PALETTE.surface, highlightthickness=1, highlightbackground=PALETTE.border, highlightcolor=PALETTE.border)
    frame.configure(padx=padx, pady=pady)
    return frame


class StatusDot(tk.Canvas):
    def __init__(self, parent: tk.Misc, size: int = 12, bg: str | None = None) -> None:
        super().__init__(parent, width=size, height=size, bg=bg or PALETTE.surface, highlightthickness=0, bd=0)
        self._size = size
        self._item = self.create_oval(1, 1, size - 1, size - 1, fill=STATE_COLORS["idle"], outline="")

    def set_state(self, state: str) -> None:
        self.itemconfigure(self._item, fill=STATE_COLORS.get(state, STATE_COLORS["idle"]))


class Monogram(tk.Canvas):
    """Marca simple: cuadrado redondeado cian con la inicial (no es un logotipo oficial)."""

    def __init__(self, parent: tk.Misc, fonts: Fonts, size: int = 38, letter: str = "F") -> None:
        super().__init__(parent, width=size, height=size, bg=PALETTE.bg, highlightthickness=0, bd=0)
        r = 9
        points = [r, 0, size - r, 0, size, 0, size, r, size, size - r, size, size, size - r, size, r, size, 0, size, 0, size - r, 0, r, 0, 0]
        self.create_polygon(points, smooth=True, fill=PALETTE.accent, outline="")
        self.create_text(size / 2, size / 2 + 1, text=letter, fill=PALETTE.on_accent, font=fonts.get(16, "bold"))


def style_menu(menu: tk.Menu, fonts: Fonts) -> None:
    menu.configure(
        bg=PALETTE.surface_2, fg=PALETTE.text, activebackground=PALETTE.accent, activeforeground=PALETTE.on_accent,
        bd=0, relief="flat", font=fonts.get(10), tearoff=False,
    )
