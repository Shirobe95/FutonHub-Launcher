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
from .dialogs import install_visual_style, show_styled_message
from .errors import AuthenticationError, DownloadError, LauncherError
from .github_api import GitHubClient
from .paths import AppPaths
from .resources import resource_path
from .self_update import download_update, find_update, schedule_update
from .transaction import DirectGitUpdater
from .uninstall import schedule_full_uninstall
from .versioning import (
    FutonHUBVersionState,
    canonical_version,
    fetch_remote_futonhub_version,
    read_installed_futonhub_version,
)


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
        self.local = tk.StringVar(value="No instalada")
        self.remote = tk.StringVar(value="Pendiente")
        self.details_visible = False
        self.admin_visible = not self.config.worker_mode or os.environ.get("FUTONHUB_ADMIN") == "1"
        self.activity_lines: list[str] = []
        self._build()
        self.root.after(80, self._drain)
        self.root.after(300, self.start_automatic)

    def _build(self) -> None:
        install_visual_style(self.root)
        self.root.title(f"FutonHUB Launcher {LAUNCHER_VERSION}")
        self.root.geometry("590x430")
        self.root.minsize(520, 390)
        try:
            self._icon_image = tk.PhotoImage(
                file=str(resource_path("assets/launcher_icon.png"))
            )
            self.root.iconphoto(True, self._icon_image)
        except (tk.TclError, OSError):
            self._icon_image = None
        try:
            self._logo_image = tk.PhotoImage(
                file=str(resource_path("assets/futonespai_logo.png"))
            ).subsample(3, 3)
        except (tk.TclError, OSError):
            self._logo_image = None

        outer = ttk.Frame(self.root, padding=20, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        if self._logo_image is not None:
            ttk.Label(header, image=self._logo_image, style="App.TLabel").grid(
                row=0, column=0, rowspan=2, sticky="w", padx=(0, 10)
            )
        else:
            ttk.Label(header, text="FutonEspai", style="Title.TLabel").grid(
                row=0, column=0, sticky="w", padx=(0, 10)
            )
        ttk.Label(
            header,
            text="FutonHUB",
            style="Title.TLabel",
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            text=f"Launcher v{LAUNCHER_VERSION} · instalación y actualización automática",
            style="Subtitle.TLabel",
        ).grid(row=1, column=1, sticky="w")

        cards = ttk.Frame(outer, style="App.TFrame")
        cards.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        cards.columnconfigure((0, 1), weight=1)
        for column, title, variable in (
            (0, "Versión instalada", self.local),
            (1, "Versión disponible", self.remote),
        ):
            box = ttk.Frame(cards, padding=14, style="Card.TFrame")
            box.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0, 8) if column == 0 else (8, 0),
            )
            ttk.Label(box, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(box, textvariable=variable, style="CardValue.TLabel").pack(
                anchor="w", pady=(5, 0)
            )

        ttk.Label(outer, textvariable=self.status, style="App.TLabel").grid(
            row=2,
            column=0,
            sticky="w",
            pady=(4, 8),
        )
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=3, column=0, sticky="ew", pady=(0, 12))

        buttons = ttk.Frame(outer, style="App.TFrame")
        buttons.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        buttons.columnconfigure(3, weight=1)
        self.open_button = ttk.Button(
            buttons,
            text="Abrir FutonHUB",
            command=self.open_erp,
            state="disabled",
            style="Primary.TButton",
        )
        self.open_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.retry_button = ttk.Button(
            buttons,
            text="Comprobar",
            command=self.start_automatic,
            style="Secondary.TButton",
        )
        self.retry_button.grid(row=0, column=1, padx=(0, 8), sticky="w")
        self.details_button = ttk.Button(
            buttons,
            text="Detalles técnicos",
            command=self.toggle_details,
            style="Secondary.TButton",
        )
        self.details_button.grid(row=0, column=2, padx=(0, 8), sticky="w")

        self.activity = ttk.LabelFrame(outer, text="Actividad técnica", padding=8)
        self.activity.grid(row=5, column=0, sticky="nsew", pady=(14, 0))
        self.activity.rowconfigure(0, weight=1)
        self.activity.columnconfigure(0, weight=1)
        self.log = tk.Text(
            self.activity,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            height=10,
            padx=10,
            pady=10,
            bg="#f7f8f7",
            relief="flat",
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.activity, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.activity.grid_remove()

        self.admin_frame = ttk.Frame(outer, style="App.TFrame")
        self.admin_frame.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        self.admin_frame.columnconfigure(4, weight=1)
        self.github_button = ttk.Button(
            self.admin_frame,
            text="GitHub",
            command=self.configure_token,
            style="Secondary.TButton",
        )
        self.github_button.grid(row=0, column=0, padx=(0, 8))
        self.env_button = ttk.Button(
            self.admin_frame,
            text=".env",
            command=self.configure_env,
            style="Secondary.TButton",
        )
        self.env_button.grid(row=0, column=1, padx=(0, 8))
        self.logs_button = ttk.Button(
            self.admin_frame,
            text="Logs",
            command=self.open_logs,
            style="Secondary.TButton",
        )
        self.logs_button.grid(row=0, column=2, padx=(0, 8))
        self.uninstall_button = ttk.Button(
            self.admin_frame,
            text="Desinstalar…",
            command=self.uninstall_all,
            style="Danger.TButton",
        )
        self.uninstall_button.grid(row=0, column=3)
        if not self.admin_visible:
            self.admin_frame.grid_remove()
        self.root.bind("<Control-Shift-A>", lambda _event: self.toggle_admin())

        self._append(
            "Launcher iniciado. GitHub se usará exclusivamente en modo lectura."
        )

    def _append(self, text: str) -> None:
        clean = str(text)
        self.activity_lines.append(clean)
        self.activity_lines = self.activity_lines[-120:]
        self.log.configure(state="normal")
        self.log.insert("end", f"• {clean}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def toggle_details(self) -> None:
        self.details_visible = not self.details_visible
        if self.details_visible:
            self.activity.grid()
            self.details_button.configure(text="Ocultar detalles")
            self.root.geometry("720x560")
        else:
            self.activity.grid_remove()
            self.details_button.configure(text="Detalles técnicos")
            self.root.geometry("590x430")

    def toggle_admin(self) -> None:
        self.admin_visible = not self.admin_visible
        if self.admin_visible:
            self.admin_frame.grid()
            self._append("Panel de administración visible.")
        else:
            self.admin_frame.grid_remove()
            self._append("Panel de administración oculto.")

    def _diagnostic_text(self, title: str, message: str, detail: str = "") -> str:
        lines = [
            f"{title}",
            f"Mensaje: {message}",
            f"Launcher: v{LAUNCHER_VERSION}",
            f"Estado: {self.status.get()}",
            f"FutonHUB instalado: {self.local.get()}",
            f"FutonHUB disponible: {self.remote.get()}",
        ]
        if detail:
            lines.extend(["", "Detalle:", detail])
        if self.activity_lines:
            lines.extend(["", "Actividad reciente:", *self.activity_lines[-20:]])
        return "\n".join(lines)

    def _show_error(self, title: str, message: str, detail: str = "", *, warning: bool = False) -> None:
        show_styled_message(
            self.root,
            title=title,
            message=message,
            details=self._diagnostic_text(title, message, detail),
            kind="warning" if warning else "error",
            on_open_logs=self.open_logs,
        )

    def _post(self, event: str, payload: Any = None) -> None:
        self.events.put((event, payload))

    def _set_busy(self, value: bool, text: str | None = None) -> None:
        self.busy = value
        state = "disabled" if value else "normal"
        self.retry_button.configure(state=state)
        self.details_button.configure(state="normal")
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
                elif event == "versions":
                    state = payload
                    if isinstance(state, FutonHUBVersionState):
                        self.local.set(state.installed_display)
                        self.remote.set(state.remote_display)
                        for line in state.technical_lines():
                            self._append(line)
                        if state.same_version_different_commits:
                            self._append(
                                "ADVERTENCIA: La versión semántica coincide, "
                                "pero los commits son diferentes."
                            )
                elif event == "technical":
                    self._append(str(payload))
                elif event == "success":
                    data = payload if isinstance(payload, dict) else {"message": payload}
                    state = data.get("state")
                    final_status = (
                        state.status_text
                        if isinstance(state, FutonHUBVersionState)
                        else "FutonHUB preparado"
                    )
                    self._set_busy(False, final_status)
                    self._append(str(data.get("message") or "FutonHUB preparado"))
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
                        self._show_error(
                            "FutonHUB no pudo abrirse",
                            f"El ERP terminó con código {code}.",
                            f"Log: {log_path}\n\nÚltimo detalle:\n{last_detail}",
                        )
                elif event == "launcher_restarting":
                    version = str(payload)
                    self._set_busy(False, f"Actualizando launcher a {version}…")
                    self._append(
                        f"Nuevo launcher {version} verificado. Reiniciando…"
                    )
                    self.root.after(350, self.root.destroy)
                elif event == "launcher_update_error":
                    self._append("Aviso actualización launcher: " + str(payload))
                    self._show_error(
                        "El launcher no pudo actualizarse",
                        "FutonHUB continuará usando la versión actual.",
                        str(payload),
                        warning=True,
                    )
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
                    self._show_error("FutonHUB Launcher", str(payload))
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
            self._show_error("GitHub", str(exc))

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
            self._show_error("Desinstalar FutonHUB", str(exc))
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
                        self._post("launcher_update_error", str(exc))
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

                local_commit = updater.local_commit()
                local_errors: list[str] = []
                installed_version = read_installed_futonhub_version(
                    self.paths.app, local_errors.append
                )
                if installed_version is None and local_commit:
                    try:
                        installed_version = canonical_version(
                            client.exact_semver_tag(local_commit)
                        )
                    except Exception as exc:
                        local_errors.append(
                            "No se pudo consultar el tag de la instalación: "
                            f"{exc}"
                        )

                remote_errors: list[str] = []
                remote_version = fetch_remote_futonhub_version(
                    client, commit.sha, remote_errors.append
                )
                state = FutonHUBVersionState(
                    installed_commit=local_commit,
                    remote_commit=commit.sha,
                    installed_version=installed_version,
                    remote_version=remote_version,
                )
                self._post("versions", state)
                self._post("status", state.status_text)
                for detail in local_errors + remote_errors:
                    self._post("technical", "Diagnóstico de versión: " + detail)

                outcome = updater.install_commit(client, commit)

                refreshed_commit = updater.local_commit()
                refreshed_errors: list[str] = []
                refreshed_version = read_installed_futonhub_version(
                    self.paths.app, refreshed_errors.append
                )
                if refreshed_version is None and refreshed_commit:
                    try:
                        refreshed_version = canonical_version(
                            client.exact_semver_tag(refreshed_commit)
                        )
                    except Exception as exc:
                        refreshed_errors.append(
                            "No se pudo consultar el tag tras actualizar: "
                            f"{exc}"
                        )
                final_state = FutonHUBVersionState(
                    installed_commit=refreshed_commit,
                    remote_commit=commit.sha,
                    installed_version=refreshed_version,
                    remote_version=remote_version,
                )
                self._post("versions", final_state)
                for detail in refreshed_errors:
                    self._post("technical", "Diagnóstico de versión: " + detail)
                self._post(
                    "success",
                    {"message": outcome.message, "state": final_state},
                )
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
                    local_commit = updater.local_commit()
                    installed_version = read_installed_futonhub_version(
                        self.paths.app
                    )
                    state = FutonHUBVersionState(
                        installed_commit=local_commit,
                        remote_commit="",
                        installed_version=installed_version,
                        remote_version=None,
                    )
                    self._post("versions", state)
                    self._post(
                        "success",
                        {
                            "message": (
                                "GitHub no está disponible; se abrirá la "
                                "instalación local."
                            ),
                            "state": state,
                        },
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
            self._show_error("FutonHUB", str(exc))


def run() -> None:
    paths = AppPaths.default()
    paths.ensure()
    config = LauncherConfig.load_or_create(paths.config / "launcher.json")
    root = tk.Tk()
    LauncherWindow(root, paths, config, WindowsCredentialStore())
    root.mainloop()
