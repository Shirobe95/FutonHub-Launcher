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
from .credentials import CredentialStore, WindowsCredentialStore
from .desktop import register_windows_integration, launch_erp, read_erp_log_tail
from .errors import LauncherError
from .flow import FailureDecision, StartupFlow
from .github_api import GitHubClient, clean_token
from .paths import AppPaths
from .resources import resource_path
from .theme import PALETTE, StatusDot, Monogram, apply_dark_title_bar, card, configure_styles, load_fonts, style_menu
from .transaction import DirectGitUpdater
from .uninstall import schedule_full_uninstall


class LauncherWindow:
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
        self._build()
        for notice in config.notices:
            self._append("Configuración: " + notice)
        self.root.after(80, self._drain)
        self.root.after(300, self.start_automatic)

    def _build(self) -> None:
        badge = f" [{CHANNEL.window_badge}]" if CHANNEL.window_badge else ""
        self.root.title(f"FutonHUB Launcher {LAUNCHER_VERSION}{badge}")
        self.root.geometry("820x620")
        self.root.minsize(700, 540)
        try:
            self._icon_image = tk.PhotoImage(
                file=str(resource_path("assets/launcher_icon.png"))
            )
            self.root.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            self._icon_image = None
        self.fonts = load_fonts(self.root)
        configure_styles(self.root, self.fonts)
        apply_dark_title_bar(self.root)
        p = PALETTE
        f = self.fonts
        self.headline = tk.StringVar(value="Preparando")

        outer = tk.Frame(self.root, bg=p.bg, padx=28, pady=22)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        # Cabecera: marca, nombre, canal y versión
        header = tk.Frame(outer, bg=p.bg)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        Monogram(header, f).grid(row=0, column=0, rowspan=2, padx=(0, 14))
        tk.Label(header, text="FutonHUB Launcher", bg=p.bg, fg=p.text, font=f.get(18, "bold")).grid(row=0, column=1, sticky="sw")
        if CHANNEL.window_badge:
            tk.Label(
                header, text=CHANNEL.window_badge, bg=p.surface_2, fg=p.accent, font=f.get(8, "bold"),
                padx=8, pady=2, highlightthickness=1, highlightbackground=p.border_strong,
            ).grid(row=0, column=2, sticky="w", padx=(12, 0), pady=(6, 0))
        tk.Label(header, text=f"v{LAUNCHER_VERSION}", bg=p.bg, fg=p.text_faint, font=f.get(10)).grid(row=0, column=3, sticky="e")

        # Estado principal
        hero = card(outer, padx=20, pady=18)
        hero.grid(row=1, column=0, sticky="ew", pady=(20, 12))
        hero.columnconfigure(1, weight=1)
        self.dot = StatusDot(hero, size=14)
        self.dot.grid(row=0, column=0, padx=(0, 12))
        tk.Label(hero, textvariable=self.headline, bg=p.surface, fg=p.text, font=f.get(15, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        tk.Label(hero, textvariable=self.status, bg=p.surface, fg=p.text_muted, font=f.get(10), anchor="w", justify="left", wraplength=700).grid(row=1, column=1, sticky="ew", pady=(4, 0))
        self.progress = ttk.Progressbar(hero, mode="indeterminate", style="Paliko.Horizontal.TProgressbar")
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        # Versiones (datos reales: commit instalado y commit remoto)
        versions = tk.Frame(outer, bg=p.bg)
        versions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        versions.columnconfigure((0, 1), weight=1, uniform="v")
        for column, title, variable in ((0, "INSTALADA", self.local), (1, "EN GITHUB", self.remote)):
            box = card(versions, padx=16, pady=12)
            box.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            tk.Label(box, text=title, bg=p.surface, fg=p.text_faint, font=f.get(8, "bold")).pack(anchor="w")
            tk.Label(box, textvariable=variable, bg=p.surface, fg=p.text, font=f.get(13, "bold", mono=True)).pack(anchor="w", pady=(4, 0))

        # Actividad
        activity = card(outer, padx=0, pady=0)
        activity.grid(row=3, column=0, sticky="nsew")
        activity.rowconfigure(1, weight=1)
        activity.columnconfigure(0, weight=1)
        tk.Label(activity, text="ACTIVIDAD", bg=p.surface, fg=p.text_faint, font=f.get(8, "bold"), anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 4))
        self.log = tk.Text(
            activity, state="disabled", wrap="word", font=f.get(9, mono=True), height=9, padx=16, pady=6,
            bg=p.surface, fg=p.text, insertbackground=p.text, relief="flat", bd=0, highlightthickness=0,
            selectbackground=p.border_strong, spacing1=2, spacing3=2,
        )
        self.log.grid(row=1, column=0, sticky="nsew", padx=(0, 0), pady=(0, 10))
        scroll = ttk.Scrollbar(activity, command=self.log.yview, style="Paliko.Vertical.TScrollbar")
        scroll.grid(row=1, column=1, sticky="ns", pady=(0, 10), padx=(0, 6))
        self.log.configure(yscrollcommand=scroll.set)
        self.log.tag_configure("time", foreground=p.text_faint)
        self.log.tag_configure("info", foreground=p.text)
        self.log.tag_configure("ok", foreground=p.success)
        self.log.tag_configure("warn", foreground=p.warning)
        self.log.tag_configure("error", foreground=p.danger)

        # Acciones: una principal, cuatro secundarias y el resto en «Más»
        actions = tk.Frame(outer, bg=p.bg)
        actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(5, weight=1)
        self.open_button = ttk.Button(actions, text="Abrir FutonHUB", command=self.open_erp, state="disabled", style="Primary.TButton")
        self.open_button.grid(row=0, column=0, padx=(0, 8))
        self.retry_button = ttk.Button(actions, text="Comprobar", command=self.start_automatic, style="Secondary.TButton")
        self.retry_button.grid(row=0, column=1, padx=(0, 8))
        self.github_button = ttk.Button(actions, text="GitHub", command=self.configure_token, style="Secondary.TButton")
        self.github_button.grid(row=0, column=2, padx=(0, 8))
        self.env_button = ttk.Button(actions, text=".env", command=self.configure_env, style="Secondary.TButton")
        self.env_button.grid(row=0, column=3, padx=(0, 8))
        self.more_button = ttk.Button(actions, text="Más  ▾", command=self._show_more, style="Ghost.TButton")
        self.more_button.grid(row=0, column=4)
        self.more_menu = tk.Menu(self.root)
        style_menu(self.more_menu, f)
        self.more_menu.add_command(label="Abrir carpeta de logs", command=self.open_logs)
        self.more_menu.add_command(label="Restaurar versión anterior…", command=self.restore_previous)
        self.more_menu.add_command(label="Reanudar actualizaciones", command=self.resume_updates)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Desinstalar…", command=self.uninstall_all, foreground=p.danger)

        self._set_state("idle", "Preparando")
        self._append("Launcher iniciado. GitHub se usa exclusivamente en modo lectura.")

    def _show_more(self) -> None:
        button = self.more_button
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        try:
            self.more_menu.tk_popup(x, y)
        finally:
            self.more_menu.grab_release()

    def _set_state(self, state: str, headline: str | None = None) -> None:
        self.dot.set_state(state)
        if headline:
            self.headline.set(headline)

    def _append(self, text: str, level: str | None = None) -> None:
        if level is None:
            upper = text.upper()
            level = "error" if upper.startswith("ERROR") else "warn" if upper.startswith("AVISO") else "info"
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
        for button in (self.retry_button, self.github_button, self.env_button, self.more_button):
            button.configure(state=state)
        if value:
            self.open_button.configure(state="disabled")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self._set_state("working", "Trabajando")
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        if text:
            self.status.set(text)

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
                        value = min(100.0, written * 100.0 / total)
                        self.progress.configure(
                            mode="determinate",
                            maximum=100,
                            value=value,
                        )
                    else:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    self.status.set(
                        f"Descargando… {(written / 1024 / 1024):.1f} MB"
                    )
                elif event == "commits":
                    local, remote = payload
                    self.local.set(local[:12] if local else "No instalado")
                    self.remote.set(remote[:12])
                elif event == "success":
                    self._set_busy(False, str(payload))
                    self._set_state("ready", "Todo listo")
                    self._append(str(payload), "ok")
                    self.open_button.configure(state="normal")
                    executable = (
                        Path(sys.executable)
                        if getattr(sys, "frozen", False)
                        else Path(sys.argv[0]).resolve()
                    )
                    register_windows_integration(executable, LAUNCHER_VERSION)
                    if self.config.auto_open_erp:
                        self.root.after(700, self.open_erp)
                elif event == "erp_closed":
                    code, log_path, detail = payload
                    self.root.deiconify()
                    if code == 0:
                        self.status.set("FutonHUB se cerró correctamente.")
                        self._append(self.status.get())
                    else:
                        self.status.set(f"FutonHUB se cerró con código {code}.")
                        self._append(self.status.get())
                        self._append(f"Diagnóstico guardado en: {log_path}")
                        if detail:
                            self._append("Último error del ERP:\n" + detail[-3500:])
                        last_detail = detail[-1800:] if detail else "Sin salida técnica."
                        messagebox.showerror(
                            "FutonHUB no pudo abrirse",
                            f"El ERP terminó con código {code}.\n\n"
                            f"Se guardó el diagnóstico en:\n{log_path}\n\n"
                            f"Último detalle:\n{last_detail}",
                        )
                elif event == "launcher_restarting":
                    version = str(payload)
                    self._set_busy(False, f"Actualizando launcher a {version}…")
                    self._set_state("working", "Actualizando el launcher")
                    self._append(
                        f"Nuevo launcher {version} verificado. Reiniciando…"
                    )
                    self.root.after(350, self.root.destroy)
                elif event == "token_ok":
                    try:
                        self.store.write(self.config.credential_target, str(payload))
                    except LauncherError as exc:
                        self._append(f"No se pudo guardar el token: {exc}")
                elif event == "degraded":
                    decision: FailureDecision = payload
                    self._set_busy(False, decision.message)
                    self._set_state("warning", "Listo, sin comprobar actualizaciones")
                    self._append("AVISO: " + decision.message)
                    self.open_button.configure(state="normal")
                    if decision.ask_token:
                        self.root.after(200, self._offer_new_token)
                    if self.config.auto_open_erp:
                        self.root.after(900, self.open_erp)
                elif event == "failed":
                    decision = payload
                    self._set_busy(False, decision.message)
                    self._set_state("error", "Detenido de forma segura")
                    self._append("ERROR: " + decision.message)
                    messagebox.showerror("FutonHUB Launcher", decision.message)
                    if decision.ask_token:
                        self.root.after(200, self._offer_new_token)
                elif event == "error":
                    self._set_busy(False, str(payload))
                    self._set_state("error", "Detenido de forma segura")
                    self._append("ERROR: " + str(payload))
                    messagebox.showerror("FutonHUB Launcher", str(payload))
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _token(self) -> str | None:
        try:
            token = self.store.read(self.config.credential_target)
            if not token and self.config.credential_target != STABLE.credential_target:
                # Canal de pruebas: reutiliza (solo lectura) el token del launcher estable si existe.
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
            "Introduce un token fine-grained con permiso Contents: Read-only "
            "para Shirobe95/FutonEspaiHUB.\n\n"
            "Se guardará en el Administrador de credenciales de Windows, "
            "no en archivos.",
            show="•",
            parent=self.root,
        )
        return clean_token(token) or None

    def _offer_new_token(self) -> None:
        if messagebox.askyesno(
            "Acceso GitHub",
            "El token de GitHub no es válido, ha caducado o no tiene permisos.\n\n"
            "¿Quieres introducir uno nuevo ahora?",
        ):
            self.configure_token()
            self.start_automatic()

    def configure_token(self) -> None:
        token = self._ask_token()
        if not token:
            return
        try:
            GitHubClient(
                self.config.owner,
                self.config.repository,
                self.config.branch,
                token,
            ).resolve_head()
            self.store.write(self.config.credential_target, token)
            messagebox.showinfo(
                "GitHub",
                "Acceso de solo lectura verificado y guardado.",
            )
        except LauncherError as exc:
            messagebox.showerror("GitHub", str(exc))

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
        token = self._token() or self._ask_token()
        if not token:
            self.status.set("Pendiente de acceso GitHub")
            return
        self._set_busy(True, "Consultando GitHub…")

        flow = StartupFlow(
            self.paths,
            self.config,
            self._post,
            frozen=bool(getattr(sys, "frozen", False)),
        )

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
            if not (self.paths.app / "GestorWoo/.env").is_file():
                configure = messagebox.askyesno(
                    "Falta .env",
                    "No hay un .env configurado. ¿Seleccionarlo ahora?",
                )
                if configure:
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
            messagebox.showerror("FutonHUB", str(exc))


def run() -> None:
    paths = AppPaths.default()
    paths.ensure()
    config = LauncherConfig.load_or_create(paths.config / "launcher.json")
    root = tk.Tk()
    LauncherWindow(root, paths, config, WindowsCredentialStore())
    root.mainloop()
