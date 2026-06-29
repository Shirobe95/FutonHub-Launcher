from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable

from .bootstrap import launcher_install_path
from .errors import DownloadError, ValidationError
from .github_api import GitHubClient, LauncherRelease
from .paths import AppPaths
from .versioning import is_newer


Progress = Callable[[int, int | None], None]
Status = Callable[[str], None]
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_SHA_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


@dataclass(frozen=True)
class LauncherUpdate:
    release: LauncherRelease
    downloaded_exe: Path
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_update(client: GitHubClient, current_version: str) -> LauncherRelease | None:
    release = client.latest_launcher_release()  # type: ignore[attr-defined]
    if release and is_newer(release.version, current_version):
        return release
    return None


def download_update(
    client: GitHubClient,
    release: LauncherRelease,
    paths: AppPaths,
    status: Status,
    progress: Progress | None = None,
) -> LauncherUpdate:
    folder = paths.downloads / "Launcher" / release.version
    folder.mkdir(parents=True, exist_ok=True)
    executable = folder / "FutonHUB-Launcher.exe"
    checksum = folder / "FutonHUB-Launcher.exe.sha256"
    status(f"Descargando FutonHUB Launcher {release.version}…")
    client.download_launcher_asset(release.asset_url, executable, progress)  # type: ignore[attr-defined]
    client.download_launcher_asset(release.checksum_url, checksum)  # type: ignore[attr-defined]
    try:
        checksum_text = checksum.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DownloadError(f"No se pudo leer el SHA-256 del launcher: {exc}") from exc
    match = _SHA_RE.search(checksum_text)
    if not match:
        raise ValidationError("El archivo SHA-256 del launcher es inválido")
    expected = match.group(1).lower()
    actual = sha256_file(executable)
    if actual != expected:
        executable.unlink(missing_ok=True)
        raise ValidationError("El SHA-256 del nuevo launcher no coincide")
    return LauncherUpdate(release, executable, actual)


def build_replacement_script(
    target: Path,
    source: Path,
    *,
    pid: int,
) -> str:
    safe_target = str(target).replace("'", "''")
    safe_source = str(source).replace("'", "''")
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$LauncherPid = {int(pid)}",
            f"$Target = '{safe_target}'",
            f"$Source = '{safe_source}'",
            "$Backup = $Target + '.previous'",
            "Wait-Process -Id $LauncherPid -ErrorAction SilentlyContinue",
            "Start-Sleep -Milliseconds 700",
            "if (Test-Path -LiteralPath $Backup) { Remove-Item -LiteralPath $Backup -Force }",
            "if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $Backup -Force }",
            "try {",
            "  Move-Item -LiteralPath $Source -Destination $Target -Force",
            "  Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target)",
            "  Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue",
            "} catch {",
            "  if (Test-Path -LiteralPath $Backup) { Move-Item -LiteralPath $Backup -Destination $Target -Force }",
            "  throw",
            "}",
            "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
            "",
        ]
    )


def schedule_update(paths: AppPaths, update: LauncherUpdate, *, pid: int | None = None) -> Path:
    if os.name != "nt":
        raise ValidationError("La autoactualización del launcher requiere Windows")
    target = launcher_install_path(paths)
    if not target.is_file():
        raise ValidationError("No se encontró el launcher instalado")
    temp_root = Path(tempfile.gettempdir()) / "FutonHUB-Launcher-Update"
    temp_root.mkdir(parents=True, exist_ok=True)
    script = temp_root / f"replace-{int(pid or os.getpid())}.ps1"
    script.write_text(
        build_replacement_script(target, update.downloaded_exe, pid=int(pid or os.getpid())),
        encoding="utf-8-sig",
        newline="\r\n",
    )
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
            ],
            cwd=str(temp_root),
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise ValidationError(f"No se pudo iniciar la actualización del launcher: {exc}") from exc
    return script
