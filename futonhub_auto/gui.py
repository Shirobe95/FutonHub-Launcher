from __future__ import annotations

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
from .config import LauncherConfig
from .credentials import CredentialStore, WindowsCredentialStore
from .desktop import register_windows_integration, launch_erp, read_erp_log_tail
from .errors import AuthenticationError, DownloadError, LauncherError
from .github_api import GitHubClient
from .paths import AppPaths
from .resources import resource_path
from .self_update import download_update, find_update, schedule_update
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
        self.root.after(80, self._drain)
        self.root.after(300, self.start_automatic)

    def _build(self) -> None:
        self.root.title(f"FutonHUB Launcher {LAUNCHER_VERSION}")
        self.root.geometry("790x560")
        self.root.minsize(680, 480)
        try:
            self._icon_image = tk.PhotoImage(
                file=str(resource_path("assets/launcher_icon.png"))
            )
            self.root.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            self._icon_image = None

        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        ttk.Label(
            outer,
            text="FutonHUB Launcher",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text=f"Comprueba, instala, actualiza y abre FutonHUB automáticamente · v{LAUNCHER_VERSION}",
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        cards = ttk.Frame(outer)
        cards.grid(row=2, column=0, sticky="ew")
        cards.columnconfigure((0, 1), weight=1)
        for column, title, variable in (
            (0, "Commit instalado", self.local),
            (1, "Commit remoto", self.remote),
        ):
            box = ttk.LabelFrame(cards, text=title, padding=12)
            box.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0, 8) if column == 0 else (8, 0),
            )
            ttk.Label(
                box,
                textvariable=variable,
                font=("Segoe UI", 11, "bold"),
            ).pack(anchor="w")

        ttk.Label(outer, textvariable=self.status).grid(
            row=3,
            column=0,
            sticky="w",
            pady=(14, 5),
        )
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(0, 12))

        activity = ttk.LabelFrame(outer, text="Actividad", padding=8)
        activity.grid(row=5, column=0, sticky="nsew")
        activity.rowconfigure(0, weight=1)
        activity.columnconfigure(0, weight=1)
        self.log = tk.Text(
            activity,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            height=14,
            padx=10,
            pady=10,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(activity, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(outer)
        buttons.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(4, weight=1)
        self.retry_button = ttk.Button(
            buttons,
            text="Comprobar ahora",
            command=self.start_automatic,
        )
        self.retry_button.grid(row=0, column=0, padx=(0, 8))
        self.open_button = ttk.Button(
            buttons,
            text="Abrir FutonHUB",
            command=self.open_erp,
            state="disabled",
        )
        self.open_button.grid(row=0, column=1, padx=(0, 8))
        self.github_button = ttk.Button(
            buttons,
            text="Configurar GitHub",
            command=self.configure_token,
        )
        self.github_button.grid(row=0, column=2, padx=(0, 8))
        self.env_button = ttk.Button(
            buttons,
            text="Configurar .env",
            command=self.configure_env,
        )
        self.env_button.grid(row=0, column=3, padx=(0, 8))
        self.logs_button = ttk.Button(
            buttons,
            text="Abrir logs",
            command=self.open_logs,
        )
        self.logs_button.grid(row=0, column=5, padx=(0, 8))
        self.uninstall_button = ttk.Button(
            buttons,
            text="Desinstalar…",
            command=self.uninstall_all,
        )
        self.uninstall_button.grid(row=0, column=6)

        self._append(
            "Launcher iniciado. GitHub se usará exclusivamente en modo lectura."
        )

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"• {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _post(self, event: str, payload: Any = None) -> None:
        self.events.put((event, payload))

    def _set_busy(self, value: bool, text: str | None = None) -> None:
        self.busy = value
        state = "disabled" if value else "normal"
        self.retry_button.configure(state=state)
        self.github_button.configure(state=state)
        self.env_button.configure(state=state)
        self.uninstall_button.configure(state=state)
        if value:
            self.open_button.configure(state="disabled")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
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
                    self._set_busy(False, "FutonHUB preparado")
                    self._append(str(payload))
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
                    self._append(
                        f"Nuevo launcher {version} verificado. Reiniciando…"
                    )
                    self.root.after(350, self.root.destroy)
                elif event == "error":
                    self._set_busy(False, "Operación detenida de forma segura")
                    self._append("ERROR: " + str(payload))
                    updater = DirectGitUpdater(
                        self.paths,
                        self.config,
                        lambda _text: None,
                        lambda _written, _total: None,
                    )
                    if updater.installation_ready():
                        self.open_button.configure(state="normal")
                    messagebox.showerror("FutonHUB Launcher", str(payload))
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _token(self) -> str | None:
        return self.store.read(self.config.credential_target)

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
        return token.strip() if token else None

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

        def worker() -> None:
            try:
                client = GitHubClient(
                    self.config.owner,
                    self.config.repository,
                    self.config.branch,
                    token,
                )
                commit = client.resolve_head()
                self.store.write(self.config.credential_target, token)
                if (
                    self.config.self_update_enabled
                    and getattr(sys, "frozen", False)
                ):
                    try:
                        launcher_client = GitHubClient(
                            self.config.launcher_owner,
                            self.config.launcher_repository,
                            "main",
                            require_auth=False,
                        )
                        launcher_release = find_update(
                            launcher_client, LAUNCHER_VERSION
                        )
                    except LauncherError as exc:
                        launcher_release = None
                        self._post(
                            "status",
                            "No se pudo comprobar la versión del launcher; "
                            f"se continuará con FutonHUB. Detalle: {exc}",
                        )
                    if launcher_release is not None:
                        self._post(
                            "status",
                            f"Nueva versión del launcher: {launcher_release.version}",
                        )
                        launcher_update = download_update(
                            launcher_client,
                            launcher_release,
                            self.paths,
                            lambda value: self._post("status", value),
                            lambda written, total: self._post(
                                "progress", (written, total)
                            ),
                        )
                        schedule_update(self.paths, launcher_update)
                        self._post(
                            "launcher_restarting", launcher_release.version
                        )
                        return
                updater = DirectGitUpdater(
                    self.paths,
                    self.config,
                    lambda text: self._post("status", text),
                    lambda written, total: self._post(
                        "progress", (written, total)
                    ),
                )
                recovered = updater.recover()
                if recovered:
                    self._post("status", recovered)
                local = updater.local_commit()
                self._post("commits", (local, commit.sha))
                outcome = updater.install_commit(client, commit)
                self._post("success", outcome.message)
            except DownloadError as exc:
                updater = DirectGitUpdater(
                    self.paths,
                    self.config,
                    lambda text: self._post("status", text),
                    lambda written, total: self._post(
                        "progress", (written, total)
                    ),
                )
                if updater.installation_ready():
                    local = updater.local_commit()
                    self._post("commits", (local, "Sin conexión"))
                    self._post(
                        "success",
                        "GitHub no está disponible; se abrirá la instalación local.",
                    )
                else:
                    self._post("error", str(exc))
            except Exception as exc:
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
