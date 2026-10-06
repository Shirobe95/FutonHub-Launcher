from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import socket
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import LAUNCHER_VERSION
from .errors import (
    AuthenticationError,
    DownloadError,
    RateLimitError,
    RemoteNotFoundError,
)
from .versioning import LAUNCHER_TAG_PREFIX, parse_version, parse_release_tag


Progress = Callable[[int, int | None], None]

TRANSIENT_STATUS = {408, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 20
_TOKEN_RE = re.compile(r"^[\x21-\x7e]{1,255}$")


def clean_token(raw: str | None) -> str:
    """Normaliza un token pegado a mano (espacios, saltos de línea, comillas)."""
    value = (raw or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def validate_token_format(token: str) -> None:
    if not _TOKEN_RE.fullmatch(token):
        raise AuthenticationError(
            "El token contiene espacios, saltos de línea u otros caracteres no "
            "válidos. Copia de nuevo el token completo de GitHub."
        )


class _StripAuthOnCrossHostRedirect(HTTPRedirectHandler):
    """urllib reenvía todas las cabeceras al redirigir; quitamos Authorization si cambia el host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(req.full_url).netloc.lower() != urlsplit(newurl).netloc.lower():
            for name in list(new.headers):
                if name.lower() == "authorization":
                    del new.headers[name]
            for name in list(new.unredirected_hdrs):
                if name.lower() == "authorization":
                    del new.unredirected_hdrs[name]
        return new


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    date: str
    message: str
    archive_url: str


@dataclass(frozen=True)
class LauncherRelease:
    version: str
    tag_name: str
    asset_url: str
    checksum_url: str
    published_at: str


class GitHubClient:
    API = "https://api.github.com"

    def __init__(
        self,
        owner: str,
        repository: str,
        branch: str,
        token: str = "",
        timeout: int = 30,
        *,
        require_auth: bool = True,
    ) -> None:
        self.owner = owner
        self.repository = repository
        self.branch = branch
        self.token = clean_token(token)
        self.timeout = timeout
        self._opener = build_opener(_StripAuthOnCrossHostRedirect)
        self._sleep: Callable[[float], None] = time.sleep
        if require_auth and not self.token:
            raise AuthenticationError("Falta el token de GitHub de solo lectura")
        if self.token:
            validate_token_format(self.token)

    @property
    def repo_slug(self) -> str:
        return f"{self.owner}/{self.repository}"

    def commit_url(self) -> str:
        ref = quote(self.branch, safe="")
        return f"{self.API}/repos/{self.owner}/{self.repository}/commits/{ref}"

    def _request(
        self,
        url: str,
        accept: str = "application/vnd.github+json",
    ) -> Request:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"FutonHUB-AutoLauncher/{LAUNCHER_VERSION}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return Request(url, headers=headers)

    @staticmethod
    def _body_text(exc: HTTPError) -> str:
        try:
            return exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            return ""

    @classmethod
    def _http_error(cls, exc: HTTPError) -> Exception:
        headers = exc.headers
        body = cls._body_text(exc) if exc.code in {403, 429} else ""
        retry_after = None
        raw_retry = headers.get("Retry-After") if headers else None
        if raw_retry and raw_retry.isdigit():
            retry_after = int(raw_retry)
        elif headers and headers.get("X-RateLimit-Reset", "").isdigit():
            retry_after = max(0, int(headers["X-RateLimit-Reset"]) - int(time.time()))
        rate_limited = exc.code == 429 or (
            exc.code == 403
            and (
                (headers and headers.get("X-RateLimit-Remaining") == "0")
                or raw_retry is not None
                or "rate limit" in body.lower()
                or "abuse" in body.lower()
            )
        )
        if rate_limited:
            return RateLimitError(
                "GitHub limitó temporalmente las peticiones (límite de uso). "
                "No es un problema del token: se reintentará más tarde.",
                retry_after,
            )
        if exc.code == 401:
            return AuthenticationError(
                "GitHub rechazó el token (HTTP 401): es inválido, ha caducado "
                "o fue revocado. Genera uno nuevo con permiso Contents: Read-only."
            )
        if exc.code == 403:
            return AuthenticationError(
                "GitHub denegó el acceso (HTTP 403): el token no tiene permiso "
                "Contents: Read-only sobre el repositorio o requiere autorizar SSO."
            )
        if exc.code == 404:
            return RemoteNotFoundError(
                "GitHub no encuentra el repositorio, la rama o el recurso (HTTP 404). "
                "Puede que la rama se haya renombrado o borrado, o que el token no "
                "tenga acceso al repositorio privado."
            )
        if exc.code == 415:
            return DownloadError(
                "GitHub rechazó el formato solicitado (HTTP 415). "
                "Actualiza el launcher o revisa el tipo de recurso descargado."
            )
        if exc.code in TRANSIENT_STATUS:
            return DownloadError(f"GitHub no está disponible temporalmente (HTTP {exc.code}).")
        return DownloadError(f"GitHub devolvió HTTP {exc.code}")

    def _open(self, url: str, *, accept: str, timeout: int):
        """Abre la URL con reintentos para fallos transitorios; devuelve la respuesta abierta."""
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return self._opener.open(self._request(url, accept=accept), timeout=timeout)
            except HTTPError as exc:
                mapped = self._http_error(exc)
                if not isinstance(mapped, (RateLimitError, DownloadError)) or attempt == MAX_ATTEMPTS - 1:
                    raise mapped from exc
                delay = min(getattr(mapped, "retry_after", None) or 2 ** attempt, MAX_RETRY_AFTER)
                last = mapped
                if isinstance(mapped, DownloadError) and exc.code not in TRANSIENT_STATUS | {429, 403}:
                    raise mapped from exc
                self._sleep(delay)
            except (URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                last = DownloadError(f"No se pudo contactar con GitHub: {exc}")
                if attempt == MAX_ATTEMPTS - 1:
                    raise last from exc
                self._sleep(2 ** attempt)
        assert last is not None
        raise last

    def _json(self, url: str) -> object:
        try:
            with self._open(url, accept="application/vnd.github+json", timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            if isinstance(exc, (HTTPError, URLError)):
                raise
            raise DownloadError(f"No se pudo consultar GitHub: {exc}") from exc

    def resolve_head(self) -> CommitInfo:
        raw = self._json(self.commit_url())
        if not isinstance(raw, dict):
            raise DownloadError("GitHub no devolvió un commit válido")
        sha = str(raw.get("sha") or "").strip()
        commit = raw.get("commit") if isinstance(raw.get("commit"), dict) else {}
        committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
        if len(sha) != 40:
            raise DownloadError("GitHub no devolvió un commit válido")
        return CommitInfo(
            sha=sha,
            date=str(committer.get("date") or ""),
            message=str(commit.get("message") or "").splitlines()[0][:300],
            archive_url=f"{self.API}/repos/{self.owner}/{self.repository}/zipball/{sha}",
        )

    def _download(
        self,
        url: str,
        destination: Path,
        progress: Progress | None = None,
        *,
        accept: str = "application/octet-stream",
        minimum_size: int = 1,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        written = 0
        try:
            with self._open(url, accept=accept, timeout=max(self.timeout, 180)) as response, temporary.open("wb") as handle:
                total_header = response.headers.get("Content-Length")
                total = int(total_header) if total_header and total_header.isdigit() else None
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise DownloadError(f"No se pudo descargar desde GitHub: {exc}") from exc
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        if written < minimum_size:
            temporary.unlink(missing_ok=True)
            raise DownloadError("GitHub devolvió un archivo vacío o incompleto")
        temporary.replace(destination)
        return destination

    def download_snapshot(
        self,
        commit: CommitInfo,
        destination: Path,
        progress: Progress | None = None,
    ) -> Path:
        return self._download(
            commit.archive_url,
            destination,
            progress,
            accept="application/vnd.github+json",
            minimum_size=1024,
        )

    def latest_launcher_release(
        self,
        prefix: str = LAUNCHER_TAG_PREFIX,
        allow_prerelease: bool = False,
    ) -> LauncherRelease | None:
        url = f"{self.API}/repos/{self.owner}/{self.repository}/releases?per_page=30"
        raw = self._json(url)
        if not isinstance(raw, list):
            raise DownloadError("GitHub devolvió un listado de releases inválido")
        best: LauncherRelease | None = None
        for release in raw:
            if not isinstance(release, dict) or release.get("draft") or (release.get("prerelease") and not allow_prerelease):
                continue
            tag = str(release.get("tag_name") or "")
            version = parse_release_tag(tag, prefix)
            if version is None:
                continue
            assets = release.get("assets") if isinstance(release.get("assets"), list) else []
            by_name = {
                str(asset.get("name") or ""): str(asset.get("url") or "")
                for asset in assets
                if isinstance(asset, dict)
            }
            executable = by_name.get("FutonHUB-Launcher.exe")
            checksum = by_name.get("FutonHUB-Launcher.exe.sha256")
            if executable and checksum:
                candidate = LauncherRelease(
                    version=version,
                    tag_name=tag,
                    asset_url=executable,
                    checksum_url=checksum,
                    published_at=str(release.get("published_at") or ""),
                )
                if best is None or parse_version(candidate.version) > parse_version(best.version):
                    best = candidate
        return best

    def download_launcher_asset(
        self,
        url: str,
        destination: Path,
        progress: Progress | None = None,
    ) -> Path:
        return self._download(url, destination, progress)
