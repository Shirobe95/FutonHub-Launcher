from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import LAUNCHER_VERSION
from .errors import AuthenticationError, DownloadError
from .versioning import parse_version


Progress = Callable[[int, int | None], None]


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
        self.token = token.strip()
        self.timeout = timeout
        if require_auth and not self.token:
            raise AuthenticationError("Falta el token de GitHub de solo lectura")

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
    def _http_error(exc: HTTPError) -> Exception:
        if exc.code in {401, 403}:
            return AuthenticationError(
                "GitHub rechazó el acceso. Revisa el token y su permiso "
                "Contents: Read-only."
            )
        if exc.code == 404:
            return AuthenticationError(
                "No se encontró el repositorio, la rama o el recurso con este token."
            )
        if exc.code == 415:
            return DownloadError(
                "GitHub rechazó el formato solicitado (HTTP 415). "
                "Actualiza el launcher o revisa el tipo de recurso descargado."
            )
        return DownloadError(f"GitHub devolvió HTTP {exc.code}")

    def _json(self, url: str) -> object:
        try:
            with urlopen(self._request(url), timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
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
            with urlopen(
                self._request(url, accept=accept),
                timeout=max(self.timeout, 180),
            ) as response, temporary.open("wb") as handle:
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
        except HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise self._http_error(exc) from exc
        except (URLError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            raise DownloadError(f"No se pudo descargar desde GitHub: {exc}") from exc
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

    def latest_launcher_release(self) -> LauncherRelease | None:
        url = f"{self.API}/repos/{self.owner}/{self.repository}/releases?per_page=30"
        raw = self._json(url)
        if not isinstance(raw, list):
            raise DownloadError("GitHub devolvió un listado de releases inválido")
        for release in raw:
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            tag = str(release.get("tag_name") or "")
            prefix = "launcher-v"
            if not tag.startswith(prefix):
                continue
            version = tag[len(prefix):].strip()
            try:
                parse_version(version)
            except ValueError:
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
                return LauncherRelease(
                    version=version,
                    tag_name=tag,
                    asset_url=executable,
                    checksum_url=checksum,
                    published_at=str(release.get("published_at") or ""),
                )
        return None

    def download_launcher_asset(
        self,
        url: str,
        destination: Path,
        progress: Progress | None = None,
    ) -> Path:
        return self._download(url, destination, progress)
