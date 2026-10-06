from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable

from .archive import safe_extract_snapshot
from .config import LauncherConfig
from .deployment import create_runtime, preserve_existing, refresh_managed_files
from .errors import AlreadyRunningError, UpdateError, ValidationError
from .github_api import CommitInfo, GitHubClient
from .locking import update_lock
from .logging_utils import AuditLogger
from .paths import AppPaths
from .python_runtime import (
    ensure_base_python,
    install_managed_python,
    prepare_runtime,
    sha256_file,
)


Status = Callable[[str], None]
Progress = Callable[[int, int | None], None]


@dataclass(frozen=True)
class UpdateOutcome:
    changed: bool
    commit: str
    previous_commit: str
    message: str


class DirectGitUpdater:
    def __init__(
        self,
        paths: AppPaths,
        config: LauncherConfig,
        status: Status,
        progress: Progress,
    ) -> None:
        self.paths = paths
        self.config = config
        self.status = status
        self.progress = progress
        self.audit = AuditLogger(paths.logs / "launcher_audit.jsonl")
        self.journal = paths.state / "transaction.json"

    def local_commit(self) -> str:
        path = self.paths.app / "SOURCE_COMMIT"
        try:
            value = path.read_text(encoding="ascii").strip()
        except OSError:
            return ""
        return value if len(value) == 40 else ""

    def _write_journal(self, phase: str, **details: object) -> None:
        payload = {"phase": phase, **details}
        temporary = self.journal.with_suffix(".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.journal)

    def recover(self) -> str | None:
        """Repara una actualización interrumpida. Si otra instancia está actualizando, no toca nada."""
        try:
            with update_lock(self.paths.state):
                return self._recover_locked()
        except AlreadyRunningError:
            return None

    def _recover_locked(self) -> str | None:
        previous = self.paths.app.with_name("App.__previous__")
        if not self.journal.exists() and not previous.exists():
            return None
        phase = "unknown"
        try:
            phase = str(
                json.loads(self.journal.read_text(encoding="utf-8")).get("phase")
                or "unknown"
            )
        except (OSError, json.JSONDecodeError):
            pass
        if phase == "postvalidated" and self.paths.app.exists():
            shutil.rmtree(previous, ignore_errors=True)
            shutil.rmtree(self.paths.staging, ignore_errors=True)
            self.paths.staging.mkdir(parents=True, exist_ok=True)
            self.journal.unlink(missing_ok=True)
            message = "Se finalizó una instalación que ya estaba validada."
            self.audit.write("recovery_finalized", phase=phase, message=message)
            return message
        if previous.exists():
            failed = self.paths.app.with_name("App.__failed__")
            shutil.rmtree(failed, ignore_errors=True)
            if self.paths.app.exists():
                self.paths.app.rename(failed)
            previous.rename(self.paths.app)
            shutil.rmtree(failed, ignore_errors=True)
            message = "Se restauró automáticamente la instalación anterior."
        else:
            message = (
                "Se limpió una actualización interrumpida antes de activar archivos."
            )
        shutil.rmtree(self.paths.staging, ignore_errors=True)
        self.paths.staging.mkdir(parents=True, exist_ok=True)
        self.journal.unlink(missing_ok=True)
        self.audit.write(
            "recovery_completed",
            phase=phase,
            message=message,
        )
        return message

    def _health(self, app: Path, python: Path) -> None:
        try:
            result = subprocess.run(
                [str(python), str(app / "health_check.py")],
                cwd=str(app),
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                "Health check agotó el tiempo (240 s); puede ser un antivirus analizando Python."
            ) from exc
        except OSError as exc:
            raise ValidationError(f"No se pudo ejecutar el health check: {exc}") from exc
        if result.returncode != 0:
            raise ValidationError(
                "Health check falló: "
                + (result.stderr or result.stdout or "sin detalle")[-4000:]
            )
        self.audit.write(
            "health_check_ok",
            app=str(app),
            output=(result.stdout or "")[:12000],
        )

    def _backup(self, commit: str) -> Path | None:
        if not self.paths.app.is_dir():
            return None
        self.paths.rollback.mkdir(parents=True, exist_ok=True)
        target = self.paths.rollback / (commit[:12] or "initial")
        suffix = 1
        while target.exists():
            target = self.paths.rollback / f"{commit[:12] or 'initial'}-{suffix}"
            suffix += 1
        shutil.copytree(self.paths.app, target)
        backups = sorted(
            [item for item in self.paths.rollback.iterdir() if item.is_dir()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in backups[self.config.backup_retention :]:
            shutil.rmtree(old, ignore_errors=True)
        return target

    def installation_ready(self) -> bool:
        required = [
            self.paths.app / "Abrir ERP.bat",
            self.paths.app / "GestorWoo/gestorwoo.py",
            self.paths.app / "SOURCE_COMMIT",
            self.paths.app / "runtime_python.txt",
        ]
        if not all(path.is_file() for path in required):
            return False
        try:
            runtime = Path(
                (self.paths.app / "runtime_python.txt")
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError:
            return False
        return runtime.is_file()

    def install_commit(
        self,
        client: GitHubClient,
        commit: CommitInfo,
    ) -> UpdateOutcome:
        """Instala ``commit`` bajo un bloqueo entre procesos (una sola actualización a la vez)."""
        with update_lock(self.paths.state):
            return self._install_commit_locked(client, commit)

    def _install_commit_locked(
        self,
        client: GitHubClient,
        commit: CommitInfo,
    ) -> UpdateOutcome:
        previous_commit = self.local_commit()
        if previous_commit == commit.sha and self.installation_ready():
            managed_changed = refresh_managed_files(self.paths.app)
            runtime_path = Path(
                (self.paths.app / "runtime_python.txt")
                .read_text(encoding="utf-8")
                .strip()
            )
            try:
                self._health(self.paths.app, runtime_path)
            except ValidationError:
                self.status(
                    "La instalación local necesita reparación; "
                    "se reconstruirá automáticamente…"
                )
                shutil.rmtree(runtime_path.parent, ignore_errors=True)
            else:
                return UpdateOutcome(
                    False,
                    commit.sha,
                    previous_commit,
                    (
                        "FutonHUB ya está actualizado; componentes del launcher reparados."
                        if managed_changed
                        else "FutonHUB ya está actualizado."
                    ),
                )

        self.paths.ensure()
        self.status("Preparando actualización desde GitHub…")
        archive = self.paths.downloads / f"{commit.sha}.zip"
        if not archive.is_file():
            client.download_snapshot(commit, archive, self.progress)
        archive_hash = sha256_file(archive)
        self.audit.write(
            "snapshot_downloaded",
            commit=commit.sha,
            sha256=archive_hash,
        )

        temporary_root = Path(
            tempfile.mkdtemp(prefix="update-", dir=self.paths.staging)
        )
        staged = temporary_root / "app"
        previous_dir = self.paths.app.with_name("App.__previous__")
        try:
            self._write_journal(
                "extracting",
                commit=commit.sha,
                temporary_root=str(temporary_root),
            )
            extracted = safe_extract_snapshot(archive, temporary_root / "source")
            self.status("Construyendo copia limpia de FutonHUB…")
            create_runtime(
                extracted,
                staged,
                commit=commit.sha,
                repository=client.repo_slug,
                branch=self.config.branch,
                commit_date=commit.date,
                archive_sha256=archive_hash,
            )
            preserved = preserve_existing(self.paths.app, staged)
            base_python = ensure_base_python(
                self.paths.runtime,
                self.config,
                self.status,
                self.progress,
            )
            try:
                runtime = prepare_runtime(
                    staged,
                    self.paths.runtime,
                    base_python,
                    self.status,
                )
            except ValidationError:
                managed_python = self.paths.runtime / "Python313/python.exe"
                if base_python.resolve() == managed_python.resolve():
                    raise
                self.status(
                    "El Python existente no pudo preparar FutonHUB; "
                    "probando con el runtime administrado…"
                )
                requirements_hash = sha256_file(staged / "requirements_erp.txt")
                for stale in (self.paths.runtime / "venvs").glob(requirements_hash[:16] + "*"):
                    shutil.rmtree(stale, ignore_errors=True)
                managed_python = install_managed_python(
                    self.paths.runtime,
                    self.config,
                    self.status,
                    self.progress,
                )
                runtime = prepare_runtime(
                    staged,
                    self.paths.runtime,
                    managed_python,
                    self.status,
                )
            self.status("Validando la instalación preparada…")
            self._health(staged, runtime.python)
            self._write_journal(
                "validated",
                commit=commit.sha,
                temporary_root=str(temporary_root),
            )
            self.status("Creando copia de seguridad…")
            backup = self._backup(previous_commit)
            shutil.rmtree(previous_dir, ignore_errors=True)
            if self.paths.app.exists():
                self.paths.app.rename(previous_dir)
            self._write_journal(
                "swapped",
                commit=commit.sha,
                temporary_root=str(temporary_root),
            )
            staged.rename(self.paths.app)
            self.status("Comprobando la instalación activa…")
            self._health(self.paths.app, runtime.python)
            self._write_journal(
                "postvalidated",
                commit=commit.sha,
                temporary_root=str(temporary_root),
            )
            shutil.rmtree(previous_dir, ignore_errors=True)
            shutil.rmtree(temporary_root, ignore_errors=True)
            archive.unlink(missing_ok=True)
            self.journal.unlink(missing_ok=True)
            self.audit.write(
                "update_succeeded",
                previous=previous_commit,
                current=commit.sha,
                preserved=preserved,
                backup=str(backup or ""),
            )
            return UpdateOutcome(
                True,
                commit.sha,
                previous_commit,
                f"FutonHUB actualizado al commit {commit.sha[:12]}.",
            )
        except Exception as exc:
            if previous_dir.exists():
                failed = self.paths.app.with_name("App.__failed__")
                shutil.rmtree(failed, ignore_errors=True)
                if self.paths.app.exists():
                    self.paths.app.rename(failed)
                previous_dir.rename(self.paths.app)
                shutil.rmtree(failed, ignore_errors=True)
            elif self.paths.app.exists() and self.local_commit() == commit.sha:
                shutil.rmtree(self.paths.app, ignore_errors=True)
            shutil.rmtree(temporary_root, ignore_errors=True)
            archive.unlink(missing_ok=True)
            self.journal.unlink(missing_ok=True)
            self.audit.write(
                "update_failed",
                commit=commit.sha,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if isinstance(exc, (ValidationError, UpdateError)):
                raise
            raise UpdateError(str(exc)) from exc


    # ------------------------------------------------------------------ pin / restore
    @property
    def pin_path(self) -> Path:
        return self.paths.state / "pin.json"

    def pinned_commit(self) -> str:
        try:
            value = json.loads(self.pin_path.read_text(encoding="utf-8")).get("commit")
        except (OSError, ValueError, AttributeError):
            return ""
        return value if isinstance(value, str) and len(value) == 40 else ""

    def set_pin(self, commit: str, reason: str) -> None:
        self.pin_path.parent.mkdir(parents=True, exist_ok=True)
        self.pin_path.write_text(
            json.dumps(
                {
                    "commit": commit,
                    "reason": reason,
                    "pinned_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def clear_pin(self) -> None:
        self.pin_path.unlink(missing_ok=True)

    def list_backups(self) -> list[tuple[str, str, float]]:
        """Copias de seguridad válidas: (nombre, commit completo, mtime), la más reciente primero."""
        found: list[tuple[str, str, float]] = []
        if not self.paths.rollback.is_dir():
            return found
        for item in self.paths.rollback.iterdir():
            commit_file = item / "SOURCE_COMMIT"
            if not item.is_dir() or not commit_file.is_file():
                continue
            try:
                commit = commit_file.read_text(encoding="ascii").strip()
            except (OSError, UnicodeError):
                continue
            if len(commit) == 40:
                found.append((item.name, commit, item.stat().st_mtime))
        return sorted(found, key=lambda row: row[2], reverse=True)

    def restore_backup(self, name: str) -> UpdateOutcome:
        """Restaura una copia de ``Rollback/`` conservando .env y datos actuales, y fija la versión."""
        source = self.paths.rollback / name
        if Path(name).name != name or not source.is_dir():
            raise ValidationError("La copia de seguridad indicada no existe")
        with update_lock(self.paths.state):
            previous_commit = self.local_commit()
            restored_commit = (source / "SOURCE_COMMIT").read_text(encoding="ascii").strip()
            if len(restored_commit) != 40:
                raise ValidationError("La copia de seguridad no tiene un commit válido")
            runtime_file = source / "runtime_python.txt"
            try:
                runtime = Path(runtime_file.read_text(encoding="utf-8").strip())
            except OSError as exc:
                raise ValidationError("La copia no incluye el entorno Python de la época") from exc
            if not runtime.is_file():
                raise ValidationError(
                    "El entorno Python de esa copia ya no existe; se necesita una actualización normal"
                )
            self.paths.ensure()
            temporary_root = Path(tempfile.mkdtemp(prefix="restore-", dir=self.paths.staging))
            staged = temporary_root / "app"
            previous_dir = self.paths.app.with_name("App.__previous__")
            try:
                self._write_journal("extracting", commit=restored_commit, temporary_root=str(temporary_root))
                shutil.copytree(source, staged)
                preserve_existing(self.paths.app, staged)
                refresh_managed_files(staged)
                self._health(staged, runtime)
                self._write_journal("validated", commit=restored_commit, temporary_root=str(temporary_root))
                self._backup(previous_commit)
                shutil.rmtree(previous_dir, ignore_errors=True)
                if self.paths.app.exists():
                    self.paths.app.rename(previous_dir)
                self._write_journal("swapped", commit=restored_commit, temporary_root=str(temporary_root))
                staged.rename(self.paths.app)
                self._health(self.paths.app, runtime)
                self._write_journal("postvalidated", commit=restored_commit, temporary_root=str(temporary_root))
                shutil.rmtree(previous_dir, ignore_errors=True)
                shutil.rmtree(temporary_root, ignore_errors=True)
                self.journal.unlink(missing_ok=True)
            except Exception as exc:
                if previous_dir.exists():
                    failed = self.paths.app.with_name("App.__failed__")
                    shutil.rmtree(failed, ignore_errors=True)
                    if self.paths.app.exists():
                        self.paths.app.rename(failed)
                    previous_dir.rename(self.paths.app)
                    shutil.rmtree(failed, ignore_errors=True)
                shutil.rmtree(temporary_root, ignore_errors=True)
                self.journal.unlink(missing_ok=True)
                self.audit.write("restore_failed", backup=name, error=str(exc))
                if isinstance(exc, (ValidationError, UpdateError)):
                    raise
                raise UpdateError(str(exc)) from exc
            self.set_pin(restored_commit, f"Restaurado manualmente desde {name}")
            self.audit.write("restore_succeeded", backup=name, previous=previous_commit, current=restored_commit)
            return UpdateOutcome(
                True,
                restored_commit,
                previous_commit,
                f"Versión restaurada al commit {restored_commit[:12]}. Las actualizaciones automáticas quedan en pausa.",
            )
