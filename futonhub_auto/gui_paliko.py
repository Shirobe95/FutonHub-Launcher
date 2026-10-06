from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from . import LAUNCHER_VERSION
from .channel import CHANNEL, STABLE
from .config import LauncherConfig
from .credentials import CredentialStore
from .desktop import register_windows_integration, launch_erp, read_erp_log_tail
from .dialogs import show_styled_message
from .errors import LauncherError
from .flow import FailureDecision, StartupFlow
from .github_api import GitHubClient, clean_token
from .health import (
    ACTION_ENV,
    ACTION_RETRY,
    ACTION_TOKEN,
    FAIL,
    OK,
    WARN,
    Check,
    build_checks,
    build_report,
    problem_headline,
)
from .paths import AppPaths
from .resources import resource_path
from .theme import PALETTE, Monogram, apply_dark_title_bar, card, configure_styles, load_fonts
from .transaction import DirectGitUpdater
from .uninstall import schedule_full_uninstall
from .versioning import FutonHUBVersionState

SPINNER_STEP_MS = 40
ICONS = {OK: ("✓", PALETTE.success), WARN: ("!", PALETTE.warning), FAIL: ("✗", PALETTE.danger), "unknown": ("–", PALETTE.text_faint)}


class PalikoLauncherWindow:
    """Tres pantallas: Cargando (siempre que trabaja), Todo al día y Problemas con chequeo."""

    def __init__(
        self,
        root: tk.Tk,
        paths: AppPaths,
        config: LauncherConfig,
        store: CredentialStore,
    ) -> None:
        self.root = root
        self.paths = paths
        self.config = config
        self.store = store
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.erp_process = None
        self.erp_log_path: Path | None = None
        self.status = tk.StringVar(value="Preparando FutonHUB…")
        self.local = tk.StringVar(value="No instalado")
        self.remote = tk.StringVar(value="Pendiente")
        self.admin_visible = not config.worker_mode or os.environ.get("FUTONHUB_ADMIN") == "1"
        self.activity_lines: list[str] = []
        self.view = "working"
        self.state: FutonHUBVersionState | None = None
        self._first_commit: str | None = None
        self._angle = 0
        self._secret: str | None = None
        self.problem: dict[str, Any] = {}
        self._build()
        for notice in config.notices:
            self._append("Configuración: " + notice)
        self.root.after(80, self._drain)
        self.root.after(SPINNER_STEP_MS, self._spin)
        self.root.after(300, self.start_automatic)

    # ------------------------------------------------------------------ construcción
    def _build(self) -> None:
        badge = f" [{CHANNEL.window_badge}]" if CHANNEL.window_badge else ""
        self.root.title(f"FutonHUB Launcher {LAUNCHER_VERSION}{badge}")
        self.root.geometry("560x560")
        self.root.minsize(520, 500)
        try:
            self._icon_image = tk.PhotoImage(file=str(resource_path("assets/launcher_icon.png")))
            self.root.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            self._icon_image = None
        self.fonts = load_fonts(self.root)
        configure_styles(self.root, self.fonts)
        apply_dark_title_bar(self.root)
        p, f = PALETTE, self.fonts

        outer = tk.Frame(self.root, bg=p.bg, padx=28, pady=22)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = tk.Frame(outer, bg=p.bg)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        Monogram(header, f).grid(row=0, column=0, padx=(0, 12))
        tk.Label(header, text="FutonHUB", bg=p.bg, fg=p.text, font=f.get(18, "bold")).grid(row=0, column=1, sticky="w")
        if CHANNEL.window_badge:
            tk.Label(
                header, text=CHANNEL.window_badge, bg=p.surface_2, fg=p.accent, font=f.get(8, "bold"),
                padx=8, pady=2, highlightthickness=1, highlightbackground=p.border_strong,
            ).grid(row=0, column=2, sticky="w", padx=(12, 0))
        tk.Label(header, text=f"launcher v{LAUNCHER_VERSION}", bg=p.bg, fg=p.text_faint, font=f.get(9)).grid(row=0, column=3, sticky="e")

        stage = tk.Frame(outer, bg=p.bg)
        stage.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        stage.columnconfigure(0, weight=1)
        stage.rowconfigure(0, weight=1)
        self.frames: dict[str, tk.Frame] = {}
        for name in ("working", "ok", "problem"):
            frame = tk.Frame(stage, bg=p.bg)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            self.frames[name] = frame
        self._build_working(self.frames["working"])
        self._build_ok(self.frames["ok"])
        self._build_problem(self.frames["problem"])
        self._build_admin(outer)
        self._show_view("working")
        self._append("Launcher iniciado. GitHub se usa exclusivamente en modo lectura.")
        self.root.bind("<Control-Shift-A>", lambda _event: self.toggle_admin())

    def _build_working(self, frame: tk.Frame) -> None:
        p, f = PALETTE, self.fonts
        frame.rowconfigure(0, weight=1)
        inner = tk.Frame(frame, bg=p.bg)
        inner.grid(row=0, column=0)
        self.spinner = tk.Canvas(inner, width=84, height=84, bg=p.bg, highlightthickness=0)
        self.spinner.pack()
        self.spinner.create_oval(8, 8, 76, 76, outline=p.surface_2, width=6)
        self._arc = self.spinner.create_arc(8, 8, 76, 76, start=90, extent=100, style="arc", outline=p.accent, width=6)
        self.work_title = tk.StringVar(value="Cargando…")
        tk.Label(inner, textvariable=self.work_title, bg=p.bg, fg=p.text, font=f.get(20, "bold")).pack(pady=(18, 4))
        tk.Label(
            inner, textvariable=self.status, bg=p.bg, fg=p.text_muted, font=f.get(10), wraplength=440, justify="center",
        ).pack()
        self.progress = ttk.Progressbar(inner, mode="indeterminate", length=360, style="Paliko.Horizontal.TProgressbar")
        self.progress.pack(pady=(20, 0))

    def _build_ok(self, frame: tk.Frame) -> None:
        p, f = PALETTE, self.fonts
        frame.rowconfigure(0, weight=1)
        inner = tk.Frame(frame, bg=p.bg)
        inner.grid(row=0, column=0)
        mark = tk.Canvas(inner, width=96, height=96, bg=p.bg, highlightthickness=0)
        mark.pack()
        mark.create_oval(6, 6, 90, 90, outline=p.success, width=5)
        mark.create_text(48, 50, text="✓", fill=p.success, font=f.get(38, "bold"))
        self.ok_title = tk.StringVar(value="Todo al día")
        self.ok_sub = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.ok_title, bg=p.bg, fg=p.text, font=f.get(22, "bold")).pack(pady=(16, 2))
        tk.Label(inner, textvariable=self.ok_sub, bg=p.bg, fg=p.text_muted, font=f.get(10)).pack()
        self.open_button = ttk.Button(inner, text="Abrir FutonHUB", command=self.open_erp, state="disabled", style="Primary.TButton")
        self.open_button.pack(pady=(26, 8), ipadx=26, ipady=4)
        self.retry_button = ttk.Button(inner, text="Comprobar de nuevo", command=self.start_automatic, style="Ghost.TButton")
        self.retry_button.pack()

    def _build_problem(self, frame: tk.Frame) -> None:
        p, f = PALETTE, self.fonts
        self.problem_title = tk.StringVar()
        self.problem_sub = tk.StringVar()
        top = tk.Frame(frame, bg=p.bg)
        top.grid(row=0, column=0, sticky="ew", pady=(6, 10))
        top.columnconfigure(1, weight=1)
        self.problem_dot = tk.Canvas(top, width=16, height=16, bg=p.bg, highlightthickness=0)
        self.problem_dot.grid(row=0, column=0, padx=(0, 10), sticky="n", pady=(8, 0))
        self._problem_dot_item = self.problem_dot.create_oval(1, 1, 15, 15, fill=p.warning, outline="")
        tk.Label(top, textvariable=self.problem_title, bg=p.bg, fg=p.text, font=f.get(17, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        tk.Label(top, textvariable=self.problem_sub, bg=p.bg, fg=p.text_muted, font=f.get(10), anchor="w", justify="left", wraplength=470).grid(row=1, column=1, sticky="ew")
        self.checks_box = card(frame, padx=14, pady=6)
        self.checks_box.grid(row=1, column=0, sticky="ew")
        self.checks_box.columnconfigure(1, weight=1)
        buttons = tk.Frame(frame, bg=p.bg)
        buttons.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.problem_open_button = ttk.Button(buttons, text="Abrir FutonHUB", command=self.open_erp, style="Primary.TButton")
        self.problem_open_button.grid(row=0, column=0, padx=(0, 8))
        self.problem_retry_button = ttk.Button(buttons, text="Reintentar", command=self.start_automatic, style="Secondary.TButton")
        self.problem_retry_button.grid(row=0, column=1, padx=(0, 8))
        self.copy_button = ttk.Button(buttons, text="Copiar informe", command=self.copy_report, style="Secondary.TButton")
        self.copy_button.grid(row=0, column=2)
        self.copy_note = tk.StringVar()
        tk.Label(frame, textvariable=self.copy_note, bg=p.bg, fg=p.success, font=f.get(9), anchor="w").grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _build_admin(self, outer: tk.Frame) -> None:
        p, f = PALETTE, self.fonts
        self.admin_frame = tk.Frame(outer, bg=p.bg)
        self.admin_frame.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        self.admin_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(
            self.admin_frame, state="disabled", wrap="word", font=f.get(9, mono=True), height=6, padx=10, pady=6,
            bg=p.surface, fg=p.text, relief="flat", bd=0, highlightthickness=1, highlightbackground=p.border,
        )
        self.log.grid(row=0, column=0, sticky="ew")
        for tag, colour in (("time", p.text_faint), ("info", p.text), ("ok", p.success), ("warn", p.warning), ("error", p.danger)):
            self.log.tag_configure(tag, foreground=colour)
        bar = tk.Frame(self.admin_frame, bg=p.bg)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        specs = (
            ("github_button", "GitHub", self.configure_token),
            ("env_button", ".env", self.configure_env),
            ("logs_button", "Logs", self.open_logs),
            ("restore_button", "Restaurar anterior…", self.restore_previous),
            ("resume_button", "Reanudar actualizaciones", self.resume_updates),
            ("uninstall_button", "Desinstalar…", self.uninstall_all),
        )
        for column, (name, text, command) in enumerate(specs):
            button = ttk.Button(bar, text=text, command=command, style="Secondary.TButton")
            button.grid(row=column // 3, column=column % 3, padx=(0, 6), pady=(0, 6), sticky="w")
            setattr(self, name, button)
        if not self.admin_visible:
            self.admin_frame.grid_remove()

    # ------------------------------------------------------------------ vistas
    def _show_view(self, name: str) -> None:
        self.view = name
        for key, frame in self.frames.items():
            if key == name:
                frame.tkraise()
        for key, frame in self.frames.items():
            frame.grid() if key == name else frame.grid_remove()

    def _spin(self) -> None:
        try:
            if self.view == "working":
                self._angle = (self._angle - 14) % 360
                self.spinner.itemconfigure(self._arc, start=self._angle)
            self.root.after(SPINNER_STEP_MS, self._spin)
        except tk.TclError:
            pass  # ventana cerrada

    def toggle_admin(self) -> None:
        self.admin_visible = not self.admin_visible
        if self.admin_visible:
            self.admin_frame.grid()
            self.root.geometry("560x720")
        else:
            self.admin_frame.grid_remove()
            self.root.geometry("560x560")
        self._append("Panel de administración " + ("visible." if self.admin_visible else "oculto."))

    def _env_present(self) -> bool:
        return (self.paths.app / "GestorWoo/.env").is_file()

    def _installation_ready(self) -> bool:
        try:
            return DirectGitUpdater(self.paths, self.config, lambda _t: None, lambda _w, _t: None).installation_ready()
        except Exception:  # noqa: BLE001 - solo afecta a lo que se muestra
            return False

    def _installed_label(self) -> str:
        if self.state is not None and self.state.installed_commit:
            return self.state.installed_display
        return ""

    def show_problem(self, kind: str | None, message: str, *, ready: bool | None = None, detail: str = "") -> None:
        ready = self._installation_ready() if ready is None else ready
        checks = build_checks(
            kind, installation_ready=ready, env_present=self._env_present(),
            installed_version=self._installed_label(), detail=detail or message,
        )
        title, sub = problem_headline(kind, ready)
        self.problem = {"kind": kind, "message": message, "ready": ready, "checks": checks, "detail": detail, "title": title}
        self.problem_title.set(title)
        self.problem_sub.set(sub)
        failing = any(c.status == FAIL for c in checks)
        self.problem_dot.itemconfigure(self._problem_dot_item, fill=PALETTE.danger if failing and not ready else PALETTE.warning)
        self._render_checks(checks)
        self.copy_note.set("")
        if ready and kind != "erp_crash":
            self.problem_open_button.grid()
        else:
            self.problem_open_button.grid_remove()
        self._show_view("problem")

    def _render_checks(self, checks: list[Check]) -> None:
        p, f = PALETTE, self.fonts
        for child in self.checks_box.winfo_children():
            child.destroy()
        for row, check in enumerate(checks):
            symbol, colour = ICONS.get(check.status, ICONS["unknown"])
            tk.Label(self.checks_box, text=symbol, bg=p.surface, fg=colour, font=f.get(13, "bold"), width=2).grid(row=row, column=0, sticky="n", pady=6)
            text = tk.Frame(self.checks_box, bg=p.surface)
            text.grid(row=row, column=1, sticky="ew", pady=6)
            tk.Label(text, text=check.label, bg=p.surface, fg=p.text, font=f.get(10, "bold"), anchor="w").pack(anchor="w")
            if check.message:
                muted = p.text_muted if check.status in (OK, "unknown") else colour
                tk.Label(text, text=check.message, bg=p.surface, fg=muted, font=f.get(9), anchor="w", justify="left", wraplength=330).pack(anchor="w")
            if check.action and check.action_label:
                ttk.Button(
                    self.checks_box, text=check.action_label, style="Secondary.TButton",
                    command=lambda action=check.action: self._run_action(action),
                ).grid(row=row, column=2, padx=(10, 0), pady=6, sticky="e")

    def _run_action(self, action: str) -> None:
        if action == ACTION_TOKEN:
            if self.configure_token():
                self.start_automatic()
        elif action == ACTION_ENV:
            self.configure_env()
            if self.problem:
                self.show_problem(self.problem["kind"], self.problem["message"], ready=self.problem["ready"], detail=self.problem["detail"])
        elif action == ACTION_RETRY:
            self.start_automatic()

    def _report_text(self) -> str:
        problem = self.problem or {}
        checks = problem.get("checks") or build_checks(
            None, installation_ready=self._installation_ready(), env_present=self._env_present(),
            installed_version=self._installed_label(),
        )
        return build_report(
            launcher_version=LAUNCHER_VERSION,
            channel=CHANNEL.name,
            title=problem.get("title", "Sin fallo registrado"),
            kind=problem.get("kind"),
            message=problem.get("message", ""),
            status_text=self.status.get(),
            installed=self.local.get(),
            available=self.remote.get(),
            checks=checks,
            activity=self.activity_lines,
            extra=problem.get("detail", ""),
            secret=self._secret,
        )

    def copy_report(self) -> None:
        text = self._report_text()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.copy_note.set("Informe copiado. Pégalo en un mensaje para soporte.")

    def _show_error(self, title: str, message: str, detail: str = "", *, warning: bool = False) -> None:
        show_styled_message(
            self.root, title=title, message=message, details=(detail or self._report_text()),
            kind="warning" if warning else "error", on_open_logs=self.open_logs, dark=True,
        )

    # ------------------------------------------------------------------ estado
    def _append(self, text: str, level: str | None = None) -> None:
        if level is None:
            upper = text.upper()
            level = "error" if upper.startswith("ERROR") else "warn" if upper.startswith("AVISO") else "info"
        self.activity_lines = (self.activity_lines + [text])[-200:]
        self.log.configure(state="normal")
        self.log.insert("end", datetime.now().strftime("%H:%M  "), "time")
        self.log.insert("end", text + "\n", level)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _post(self, event: str, payload: Any = None) -> None:
        self.events.put((event, payload))

    def _set_busy(self, value: bool, text: str | None = None) -> None:
        self.busy = value
        state = "disabled" if value else "normal"
        for name in ("retry_button", "problem_retry_button", "copy_button", "github_button", "env_button",
                     "restore_button", "resume_button", "uninstall_button"):
            getattr(self, name).configure(state=state)
        if value:
            self.open_button.configure(state="disabled")
            self.problem_open_button.configure(state="disabled")
            self.work_title.set("Cargando…")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self._show_view("working")
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.problem_open_button.configure(state="normal")
        if text:
            self.status.set(text)

    def _show_ok(self, title: str, sub: str) -> None:
        self.ok_title.set(title)
        self.ok_sub.set(sub)
        self.problem = {}
        self._show_view("ok")

    def _drain(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    self.status.set(str(payload))
                    self._append(str(payload))
                elif event == "progress":
                    written, total = payload
                    self.progress.stop()
                    if total:
                        self.progress.configure(mode="determinate", maximum=100, value=min(100.0, written * 100.0 / total))
                    else:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    self.status.set(f"Descargando… {(written / 1024 / 1024):.1f} MB")
                elif event == "versions":
                    state = payload
                    if isinstance(state, FutonHUBVersionState):
                        if self.state is None:
                            self._first_commit = state.installed_commit
                        self.state = state
                        self.local.set(state.installed_display)
                        self.remote.set(state.remote_display)
                        for line in state.technical_lines():
                            self._append(line)
                        if state.same_version_different_commits:
                            self._append("AVISO: La versión semántica coincide, pero los commits son diferentes.")
                elif event == "technical":
                    self._append(str(payload))
                elif event == "token_ok":
                    self._secret = str(payload)
                    try:
                        self.store.write(self.config.credential_target, str(payload))
                    except LauncherError as exc:
                        self._append(f"No se pudo guardar el token: {exc}")
                elif event == "success":
                    data = payload if isinstance(payload, dict) else {"message": payload}
                    state = data.get("state")
                    message = str(data.get("message") or "FutonHUB preparado")
                    self._set_busy(False)
                    self._append(message, "ok")
                    updated = isinstance(state, FutonHUBVersionState) and bool(self._first_commit) and state.installed_commit != self._first_commit
                    version = state.installed_display if isinstance(state, FutonHUBVersionState) else ""
                    self._show_ok(
                        "Actualizado" if updated else "Todo al día",
                        f"FutonHUB {version}".strip() if version else message,
                    )
                    self.open_button.configure(state="normal")
                    executable = Path(sys.executable) if getattr(sys, "frozen", False) else Path(sys.argv[0]).resolve()
                    register_windows_integration(executable, LAUNCHER_VERSION)
                    if self.config.auto_open_erp:
                        self.root.after(900, self.open_erp)
                elif event == "degraded":
                    decision: FailureDecision = payload
                    self._set_busy(False)
                    self._append("AVISO: " + decision.message)
                    self.show_problem(decision.kind, decision.message, ready=True)
                    # Si el problema es pasajero (red/límite) no hay nada que arreglar: se abre el ERP.
                    if self.config.auto_open_erp and decision.kind in ("network", "rate_limit"):
                        self.root.after(1500, self.open_erp)
                elif event == "failed":
                    decision = payload
                    self._set_busy(False)
                    self._append("ERROR: " + decision.message)
                    self.show_problem(decision.kind, decision.message, ready=False)
                elif event == "error":
                    self._set_busy(False)
                    self._append("ERROR: " + str(payload))
                    self.show_problem("unexpected", str(payload), detail=str(payload))
                elif event == "erp_closed":
                    code, log_path, detail = payload
                    self.root.deiconify()
                    if code == 0:
                        self._append("FutonHUB se cerró correctamente.")
                        self._show_ok("FutonHUB se cerró", "Puedes volver a abrirlo cuando quieras.")
                        self.open_button.configure(state="normal")
                    else:
                        self._append(f"FutonHUB se cerró con código {code}. Diagnóstico: {log_path}")
                        self.show_problem(
                            "erp_crash", f"FutonHUB se cerró con código {code}.", ready=True,
                            detail=f"Log: {log_path}\n\nÚltimo detalle:\n{(detail or 'Sin salida técnica.')[-3500:]}",
                        )
                elif event == "launcher_restarting":
                    version = str(payload)
                    self._set_busy(False)
                    self._show_view("working")
                    self.work_title.set("Actualizando el launcher…")
                    self.status.set(f"Instalando la versión {version}. Se reiniciará solo.")
                    self._append(f"Nuevo launcher {version} verificado. Reiniciando…")
                    self.root.after(350, self.root.destroy)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    # ------------------------------------------------------------------ acciones
    def _token(self) -> str | None:
        try:
            token = self.store.read(self.config.credential_target)
            if not token and self.config.credential_target != STABLE.credential_target:
                # Canal de pruebas: reutiliza (solo lectura) el token del launcher estable.
                token = self.store.read(STABLE.credential_target)
                if token:
                    self._append("Se reutiliza el token de solo lectura del launcher estable.")
            return token
        except LauncherError as exc:
            self._append(f"No se pudo leer el token guardado: {exc}")
            return None

    def _ask_token(self) -> str | None:
        token = simpledialog.askstring(
            "Acceso GitHub",
            "Pega el token de acceso (solo lectura) que te ha dado soporte.\n\n"
            "Se guardará en el Administrador de credenciales de Windows, no en archivos.",
            show="•",
            parent=self.root,
        )
        return clean_token(token) or None

    def configure_token(self) -> bool:
        token = self._ask_token()
        if not token:
            return False
        self._secret = token
        try:
            GitHubClient(self.config.owner, self.config.repository, self.config.branch, token).resolve_head()
            self.store.write(self.config.credential_target, token)
            messagebox.showinfo("GitHub", "Acceso verificado y guardado.")
            return True
        except LauncherError as exc:
            self._show_error("GitHub", str(exc))
            return False

    def restore_previous(self) -> None:
        if self.busy:
            return
        updater = DirectGitUpdater(self.paths, self.config, lambda _t: None, lambda _w, _t: None)
        backups = updater.list_backups()
        if not backups:
            messagebox.showinfo("Restaurar versión", "No hay copias de seguridad disponibles todavía.")
            return
        name, commit, _mtime = backups[0]
        if not messagebox.askyesno(
            "Restaurar versión anterior",
            f"Se restaurará la copia más reciente ({commit[:12]}).\n"
            "Tu .env y tus datos locales se conservan y las actualizaciones "
            "automáticas quedarán en pausa hasta que pulses «Reanudar».\n\n¿Continuar?",
        ):
            return
        self._set_busy(True, "Restaurando versión anterior…")

        def worker() -> None:
            try:
                outcome = updater.restore_backup(name)
                self._post("success", outcome.message)
            except Exception as exc:  # noqa: BLE001
                self._post("error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def resume_updates(self) -> None:
        updater = DirectGitUpdater(self.paths, self.config, lambda _t: None, lambda _w, _t: None)
        if not updater.pinned_commit():
            messagebox.showinfo("Actualizaciones", "Las actualizaciones automáticas ya están activas.")
            return
        updater.clear_pin()
        self._append("Actualizaciones automáticas reanudadas.")
        self.start_automatic()

    def configure_env(self) -> None:
        source = filedialog.askopenfilename(
            title="Selecciona el archivo .env autorizado",
            filetypes=[("Archivo .env", ".env"), ("Todos", "*.*")],
        )
        if not source:
            return
        target = self.paths.app / "GestorWoo/.env"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        messagebox.showinfo("FutonHUB", f".env copiado en:\n{target}")

    def open_logs(self) -> None:
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(self.paths.logs)

    def uninstall_all(self) -> None:
        if self.busy:
            messagebox.showwarning(
                "Desinstalar FutonHUB",
                "Espera a que termine la operación actual.",
            )
            return
        if self.erp_process is not None and self.erp_process.poll() is None:
            messagebox.showwarning(
                "Desinstalar FutonHUB",
                "Cierra primero el ERP antes de desinstalar.",
            )
            return
        first = messagebox.askyesno(
            "Desinstalar FutonHUB",
            "Se borrará TODO el contenido local de FutonHUB en esta máquina:\n\n"
            "• aplicación y launcher\n"
            "• .env y configuración local\n"
            "• copias de seguridad, logs y descargas\n"
            "• entorno Python administrado\n"
            "• token GitHub guardado\n\n"
            "Esta acción no se puede deshacer. ¿Continuar?",
            icon="warning",
        )
        if not first:
            return
        confirmation = simpledialog.askstring(
            "Confirmación final",
            "Escribe BORRAR TODO para confirmar la desinstalación completa:",
            parent=self.root,
        )
        if (confirmation or "").strip().upper() != "BORRAR TODO":
            messagebox.showinfo(
                "Desinstalar FutonHUB",
                "Desinstalación cancelada.",
            )
            return
        try:
            schedule_full_uninstall(
                self.paths,
                self.store,
                self.config.credential_target,
            )
        except LauncherError as exc:
            messagebox.showerror("Desinstalar FutonHUB", str(exc))
            return
        messagebox.showinfo(
            "Desinstalar FutonHUB",
            "FutonHUB se cerrará y se eliminarán todos sus archivos locales.",
        )
        self.root.destroy()

    def start_automatic(self) -> None:
        if self.busy:
            return
        token = self._token()
        if not token:
            self.show_problem("no_token", "Falta el token de acceso a GitHub.")
            return
        self._secret = token
        self._set_busy(True, "Consultando GitHub…")
        flow = StartupFlow(self.paths, self.config, self._post, frozen=bool(getattr(sys, "frozen", False)))

        def worker() -> None:
            try:
                flow.run(token)
            except Exception as exc:  # noqa: BLE001 - último recurso
                self._post("error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def open_erp(self) -> None:
        if self.erp_process is not None and self.erp_process.poll() is None:
            return
        try:
            if not self._env_present():
                if messagebox.askyesno("Falta .env", "No hay un .env configurado. ¿Seleccionarlo ahora?"):
                    self.configure_env()
            launched = launch_erp(self.paths.app, self.paths.logs)
            self.erp_process = launched.process
            self.erp_log_path = launched.log_path
            self._append("FutonHUB abierto con el entorno Python administrado.")
            self._append(f"Salida técnica: {launched.log_path}")
            self.root.withdraw()

            def wait() -> None:
                code = launched.process.wait()
                detail = read_erp_log_tail(launched.log_path)
                self._post("erp_closed", (code, launched.log_path, detail))

            threading.Thread(target=wait, daemon=True).start()
        except LauncherError as exc:
            self.show_problem("unexpected", str(exc), detail=str(exc))
