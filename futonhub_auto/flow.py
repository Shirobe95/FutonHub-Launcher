"""Flujo de arranque del launcher, independiente de Tk (se prueba sin interfaz).

Orden: recuperar -> autoactualizar launcher (público, sin token) -> consultar ERP ->
instalar. Si GitHub falla pero hay instalación local, se abre la versión instalada
y se explica el motivo (token caducado, límite de uso, rama inexistente, sin red…).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import LAUNCHER_VERSION
from .config import LauncherConfig
from .errors import (
    AlreadyRunningError,
    AuthenticationError,
    DownloadError,
    LauncherError,
    RateLimitError,
    RemoteNotFoundError,
    UpdateError,
    ValidationError,
)
from .github_api import GitHubClient
from .paths import AppPaths
from .self_update import download_update, failed_versions, find_update, schedule_update
from .transaction import DirectGitUpdater
from .versioning import (
    FutonHUBVersionState,
    canonical_version,
    fetch_remote_futonhub_version,
    read_installed_futonhub_version,
)

Emit = Callable[[str, Any], None]


@dataclass(frozen=True)
class FailureDecision:
    kind: str  # token | not_found | rate_limit | network | update_failed | busy | unexpected
    open_local: bool
    ask_token: bool
    message: str


def decide_failure(exc: BaseException, installation_ready: bool) -> FailureDecision:
    """Traduce un fallo remoto en la acción correcta para el usuario."""
    if isinstance(exc, AlreadyRunningError):
        return FailureDecision("busy", False, False, str(exc))
    if isinstance(exc, AuthenticationError):
        kind, ask = "token", True
    elif isinstance(exc, RemoteNotFoundError):
        kind, ask = "not_found", False
    elif isinstance(exc, RateLimitError):
        kind, ask = "rate_limit", False
    elif isinstance(exc, DownloadError):
        kind, ask = "network", False
    elif isinstance(exc, (ValidationError, UpdateError)):
        kind, ask = "update_failed", False
    else:
        return FailureDecision("unexpected", False, False, str(exc) or type(exc).__name__)
    if installation_ready:
        suffix = " Se abre la versión instalada."
        if kind == "update_failed":
            suffix = " Se mantiene la versión anterior, que funciona."
        return FailureDecision(kind, True, ask, str(exc) + suffix)
    return FailureDecision(kind, False, ask, str(exc))


class StartupFlow:
    def __init__(
        self,
        paths: AppPaths,
        config: LauncherConfig,
        emit: Emit,
        *,
        frozen: bool,
        client_factory: Callable[..., GitHubClient] = GitHubClient,
    ) -> None:
        self.paths = paths
        self.config = config
        self.emit = emit
        self.frozen = frozen
        self.client_factory = client_factory

    def _updater(self) -> DirectGitUpdater:
        return DirectGitUpdater(
            self.paths,
            self.config,
            lambda text: self.emit("status", text),
            lambda written, total: self.emit("progress", (written, total)),
        )

    def _check_launcher_update(self) -> bool:
        """True si se programó una autoactualización y hay que cerrar."""
        if not (self.config.self_update_enabled and self.frozen):
            return False
        try:
            client = self.client_factory(
                self.config.launcher_owner,
                self.config.launcher_repository,
                "main",
                require_auth=False,
            )
            release = find_update(
                client,
                LAUNCHER_VERSION,
                prefix=self.config.release_tag_prefix,
                allow_prerelease=self.config.release_allow_prerelease,
            )
        except LauncherError as exc:
            self.emit(
                "status",
                f"No se pudo comprobar la versión del launcher; se continúa. Detalle: {exc}",
            )
            return False
        if release is None:
            return False
        if release.version in failed_versions(self.paths):
            self.emit(
                "status",
                f"El launcher {release.version} no llegó a arrancar en este equipo y se revirtió; "
                "se omite hasta que haya una versión nueva.",
            )
            return False
        self.emit("status", f"Nueva versión del launcher: {release.version}")
        try:
            update = download_update(
                client,
                release,
                self.paths,
                lambda value: self.emit("status", value),
                lambda written, total: self.emit("progress", (written, total)),
            )
            schedule_update(self.paths, update)
        except LauncherError as exc:
            self.emit("status", f"No se pudo autoactualizar el launcher ({exc}); se continúa.")
            return False
        self.emit("launcher_restarting", release.version)
        return True

    def _installed_version(self, updater: DirectGitUpdater, client: Any, commit: str, errors: list[str]) -> str | None:
        version = read_installed_futonhub_version(self.paths.app, errors.append)
        if version is None and commit and client is not None:
            try:
                version = canonical_version(client.exact_semver_tag(commit))
            except Exception as exc:  # noqa: BLE001 - solo informativo
                errors.append(f"No se pudo consultar el tag de la instalación: {exc}")
        return version

    def _emit_state(self, state: FutonHUBVersionState, errors: list[str]) -> None:
        self.emit("versions", state)
        for detail in errors:
            self.emit("technical", "Diagnóstico de versión: " + detail)

    def run(self, token: str) -> None:
        updater = self._updater()
        client = None
        try:
            recovered = updater.recover()
            if recovered:
                self.emit("status", recovered)
            if self._check_launcher_update():
                return
            client = self.client_factory(
                self.config.owner, self.config.repository, self.config.branch, token
            )
            commit = client.resolve_head()
            self.emit("token_ok", token)
            local = updater.local_commit()
            errors: list[str] = []
            remote_version = fetch_remote_futonhub_version(client, commit.sha, errors.append)
            state = FutonHUBVersionState(
                installed_commit=local,
                remote_commit=commit.sha,
                installed_version=self._installed_version(updater, client, local, errors),
                remote_version=remote_version,
            )
            self._emit_state(state, errors)
            self.emit("status", state.status_text)
            pinned = updater.pinned_commit()
            if pinned and pinned == local and updater.installation_ready():
                self.emit(
                    "success",
                    {
                        "message": "Versión fijada: las actualizaciones automáticas están en pausa. "
                        "Usa «Reanudar actualizaciones» para volver a seguir GitHub.",
                        "state": state,
                    },
                )
                return
            outcome = updater.install_commit(client, commit)
            refreshed = updater.local_commit()
            errors = []
            final = FutonHUBVersionState(
                installed_commit=refreshed,
                remote_commit=commit.sha,
                installed_version=self._installed_version(updater, client, refreshed, errors),
                remote_version=remote_version,
            )
            self._emit_state(final, errors)
            self.emit("success", {"message": outcome.message, "state": final})
        except Exception as exc:  # noqa: BLE001 - se clasifica y se informa
            decision = decide_failure(exc, updater.installation_ready())
            local = updater.local_commit()
            if local:
                self.emit(
                    "versions",
                    FutonHUBVersionState(
                        installed_commit=local,
                        remote_commit="",
                        installed_version=read_installed_futonhub_version(self.paths.app),
                        remote_version=None,
                    ),
                )
            if decision.open_local:
                self.emit("degraded", decision)
            else:
                self.emit("failed", decision)
