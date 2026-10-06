from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib
from typing import Callable, Protocol


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)([-+][0-9A-Za-z.-]+)?$")
_VERSION_ASSIGNMENT = "__version__"
_LOCAL_VERSION_SOURCES: tuple[tuple[str, str], ...] = (
    ("GestorWoo/pyproject.toml", "toml"),
    ("GestorWoo/src/futonhub/__init__.py", "python"),
    ("GestorWoo/src/gestorwoo/__init__.py", "python"),
)
_REMOTE_VERSION_SOURCES = _LOCAL_VERSION_SOURCES

VersionErrorCallback = Callable[[str], None]


class RemoteVersionClient(Protocol):
    def fetch_text_file(self, path: str, *, ref: str | None = None) -> str:
        ...

    def exact_semver_tag(self, commit_sha: str) -> str | None:
        ...


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch((value or "").strip())
    if not match:
        raise ValueError(f"Versión inválida: {value!r}")
    return tuple(int(part) for part in match.groups()[:3])


def canonical_version(value: str | None) -> str | None:
    """Return a validated SemVer value without the optional visual ``v``."""

    text = (value or "").strip()
    match = _VERSION_RE.fullmatch(text)
    if not match:
        return None
    core = ".".join(match.groups()[:3])
    suffix = match.group(4) or ""
    return core + suffix


def display_version(value: str | None) -> str:
    normalized = canonical_version(value)
    return f"v{normalized}" if normalized else "Desconocida"


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def _version_from_toml(content: str) -> str | None:
    try:
        raw = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, TypeError):
        return None
    project = raw.get("project")
    if not isinstance(project, dict):
        return None
    value = project.get("version")
    return canonical_version(value if isinstance(value, str) else None)


def _version_from_python(content: str) -> str | None:
    try:
        module = ast.parse(content)
    except (SyntaxError, ValueError, TypeError):
        return None
    for statement in module.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        if value is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == _VERSION_ASSIGNMENT
            for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return canonical_version(value.value)
    return None


def _parse_version_content(content: str, source_type: str) -> str | None:
    if source_type == "toml":
        return _version_from_toml(content)
    if source_type == "python":
        return _version_from_python(content)
    return None


def read_installed_futonhub_version(
    install_dir: Path,
    on_error: VersionErrorCallback | None = None,
) -> str | None:
    """Read FutonHUB's real version from installed package files.

    Failure is deliberately non-blocking. The caller can receive concise
    diagnostics through ``on_error`` without exposing a traceback to users.
    """

    root = Path(install_dir)
    for relative, source_type in _LOCAL_VERSION_SOURCES:
        path = root / relative
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            if on_error:
                on_error(f"No se pudo leer {relative}: {exc}")
            continue
        version = _parse_version_content(content, source_type)
        if version:
            return version
        if on_error:
            on_error(f"{relative} no contiene una versión válida")
    return None


def fetch_remote_futonhub_version(
    client: RemoteVersionClient,
    ref: str,
    on_error: VersionErrorCallback | None = None,
) -> str | None:
    """Read FutonHUB's version at an exact remote ref using the existing client."""

    for relative, source_type in _REMOTE_VERSION_SOURCES:
        try:
            content = client.fetch_text_file(relative, ref=ref)
        except Exception as exc:  # Version lookup must never block commit updates.
            if on_error:
                on_error(f"No se pudo consultar {relative}: {exc}")
            continue
        version = _parse_version_content(content, source_type)
        if version:
            return version
        if on_error:
            on_error(f"{relative} remoto no contiene una versión válida")
    try:
        tag = client.exact_semver_tag(ref)
    except Exception as exc:  # Same non-blocking rule for compatibility fallback.
        if on_error:
            on_error(f"No se pudo consultar el tag exacto de {ref[:12]}: {exc}")
        return None
    return canonical_version(tag)


def read_persisted_futonhub_version(install_dir: Path) -> str | None:
    """Read auxiliary metadata only; package files remain the source of truth."""

    root = Path(install_dir)
    info = root / "SOURCE_INFO.json"
    try:
        raw = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raw = None
    if isinstance(raw, dict):
        for key in ("installed_version", "version"):
            value = raw.get(key)
            if isinstance(value, str):
                normalized = canonical_version(value)
                if normalized:
                    return normalized
    version_path = root / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if value.startswith("0.0.0+git."):
        return None
    return canonical_version(value)


def commits_require_update(installed_commit: str, remote_commit: str) -> bool:
    """Commit identity remains the only update decision rule."""

    return bool(remote_commit) and installed_commit != remote_commit


@dataclass(frozen=True)
class FutonHUBVersionState:
    installed_commit: str
    remote_commit: str
    installed_version: str | None = None
    remote_version: str | None = None

    @property
    def update_available(self) -> bool:
        return commits_require_update(self.installed_commit, self.remote_commit)

    @property
    def same_version_different_commits(self) -> bool:
        installed = canonical_version(self.installed_version)
        remote = canonical_version(self.remote_version)
        return bool(
            installed
            and remote
            and installed == remote
            and self.update_available
        )

    @property
    def installed_display(self) -> str:
        if not self.installed_commit:
            return "No instalada"
        return display_version(self.installed_version)

    @property
    def remote_display(self) -> str:
        return display_version(self.remote_version)

    @property
    def status_text(self) -> str:
        if not self.remote_commit:
            return "No se pudo comprobar la versión disponible"
        if self.update_available:
            return "Hay una nueva versión disponible"
        return "FutonHUB está actualizado"

    def technical_lines(self) -> tuple[str, str, str, str]:
        return (
            f"Versión instalada: {self.installed_display}",
            f"Commit instalado: {self.installed_commit or 'No instalado'}",
            f"Versión disponible: {self.remote_display}",
            f"Commit remoto: {self.remote_commit or 'No disponible'}",
        )
