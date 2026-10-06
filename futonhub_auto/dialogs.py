from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


ACCENT = "#4f7f2f"
DANGER = "#b3261e"
WARNING = "#8a5a00"
TEXT = "#1f2933"
MUTED = "#667085"
SURFACE = "#ffffff"
SOFT = "#f4f6f3"


def install_visual_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=SURFACE)
    style.configure("App.TFrame", background=SURFACE)
    style.configure("Soft.TFrame", background=SOFT)
    style.configure("App.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("Title.TLabel", background=SURFACE, foreground=TEXT, font=("Segoe UI", 18, "bold"))
    style.configure("Subtitle.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
    style.configure("Card.TFrame", background=SOFT, relief="flat")
    style.configure("CardTitle.TLabel", background=SOFT, foreground=MUTED, font=("Segoe UI", 8))
    style.configure("CardValue.TLabel", background=SOFT, foreground=TEXT, font=("Segoe UI", 15, "bold"))
    style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 9))
    style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=(12, 7))
    style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"), padding=(12, 7))
    style.configure("Horizontal.TProgressbar", troughcolor="#edf1eb", background=ACCENT)


def show_styled_message(
    parent: tk.Tk | tk.Toplevel,
    *,
    title: str,
    message: str,
    details: str = "",
    kind: str = "error",
    on_open_logs: Callable[[], None] | None = None,
    dark: bool = False,
) -> None:
    if dark:
        from .theme import PALETTE as P

        surface, text_c, muted, box_bg = P.surface, P.text, P.text_muted, P.bg
        danger, warning, accent = P.danger, P.warning, P.accent
    else:
        surface, text_c, muted, box_bg = SURFACE, TEXT, MUTED, "#f7f8f7"
        danger, warning, accent = DANGER, WARNING, ACCENT
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    dialog.configure(bg=surface)

    color = danger if kind == "error" else warning if kind == "warning" else accent
    icon = "!" if kind in {"error", "warning"} else "i"

    frame = tk.Frame(dialog, bg=surface, padx=22, pady=22)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(1, weight=1)

    badge = tk.Canvas(frame, width=42, height=42, bg=surface, highlightthickness=0)
    badge.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
    badge.create_oval(4, 4, 38, 38, fill=color, outline=color)
    badge.create_text(21, 21, text=icon, fill="white", font=("Segoe UI", 19, "bold"))

    tk.Label(frame, text=title, bg=surface, fg=text_c, font=("Segoe UI", 15, "bold")).grid(row=0, column=1, sticky="w")
    tk.Label(
        frame,
        text=message,
        bg=surface,
        fg=text_c,
        wraplength=470,
        justify="left",
    ).grid(row=1, column=1, sticky="ew", pady=(6, 12))

    details_text = details.strip()
    if details_text:
        tk.Label(
            frame,
            text="Mensaje para soporte",
            bg=surface,
            fg=muted,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))
        box = tk.Text(
            frame,
            width=68,
            height=9,
            wrap="word",
            font=("Consolas", 8),
            bg=box_bg,
            fg=text_c,
            relief="flat",
            padx=10,
            pady=8,
        )
        box.grid(row=3, column=0, columnspan=2, sticky="ew")
        box.insert("1.0", details_text)
        box.configure(state="disabled")
    else:
        box = None

    buttons = tk.Frame(frame, bg=surface)
    buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))

    def copy_details() -> None:
        text = details_text or f"{title}\n{message}"
        parent.clipboard_clear()
        parent.clipboard_append(text)

    if details_text:
        ttk.Button(buttons, text="Copiar mensaje", style="Secondary.TButton", command=copy_details).pack(side="left", padx=(0, 8))
    if on_open_logs is not None:
        ttk.Button(buttons, text="Abrir logs", style="Secondary.TButton", command=on_open_logs).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Cerrar", style="Primary.TButton", command=dialog.destroy).pack(side="left")

    dialog.update_idletasks()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - dialog.winfo_width()) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - dialog.winfo_height()) // 2)
    dialog.geometry(f"+{x}+{y}")
    dialog.wait_window()
