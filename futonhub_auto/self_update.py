from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable

from .bootstrap import launcher_install_path
from .errors import DownloadError, ValidationError
from .github_api import GitHubClient, LauncherRelease
from .paths import AppPaths
from .pshell import quote
from .versioning import is_newer


Progress = Callable[[int, int | None], None]
Status = Callable[[str], None]
IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
EXPECTED_ASSET_NAME = "FutonHUB-Launcher.exe"
_SHA_LINE_RE = re.compile(r"^([0-9a-fA-F]{64})(?:\s+\*?(.+?))?\s*$")


def parse_checksum(text: str) -> str:
    """Extrae el SHA-256 del ``.sha256`` (formato ``<hash>  <archivo>``).

    Si la línea indica nombre de archivo, debe ser ``FutonHUB-Launcher.exe``.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValidationError("El archivo SHA-256 del launcher debe tener exactamente una línea")
    match = _SHA_LINE_RE.match(lines[0])
    if not match:
        raise ValidationError("El archivo SHA-256 del launcher es inválido")
    name = match.group(2)
    if name and Path(name.replace("\\", "/")).name != EXPECTED_ASSET_NAME:
        raise ValidationError(f"El SHA-256 corresponde a otro archivo ({name})")
    return match.group(1).lower()


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


def find_update(
    client: GitHubClient,
    current_version: str,
    *,
    prefix: str | None = None,
    allow_prerelease: bool | None = None,
) -> LauncherRelease | None:
    options: dict[str, object] = {}
    if prefix is not None:
        options["prefix"] = prefix
    if allow_prerelease is not None:
        options["allow_prerelease"] = allow_prerelease
    release = client.latest_launcher_release(**options)  # type: ignore[attr-defined]
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
    try:
        expected = parse_checksum(checksum_text)
    except ValidationError:
        executable.unlink(missing_ok=True)
        raise
    actual = sha256_file(executable)
    if actual != expected:
        executable.unlink(missing_ok=True)
        raise ValidationError("El SHA-256 del nuevo launcher no coincide")
    return LauncherUpdate(release, executable, actual)


OK_MARKER = "launcher_ok.json"
FAILED_FILE = "launcher_update_failed.txt"
HANDSHAKE_SECONDS = 45


def failed_versions(paths: AppPaths) -> set[str]:
    try:
        text = (paths.state / FAILED_FILE).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return set()
    return {line.strip() for line in text.splitlines() if line.strip()}


def write_ok_marker(paths: AppPaths, version: str) -> None:
    """El launcher recién arrancado avisa de que inició bien (lo espera el script de reemplazo)."""
    try:
        paths.state.mkdir(parents=True, exist_ok=True)
        (paths.state / OK_MARKER).write_text(
            json.dumps({"version": version, "pid": os.getpid()}) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


def build_replacement_script(
    target: Path,
    source: Path,
    *,
    pid: int,
    version: str | None = None,
    state_dir: Path | None = None,
) -> str:
    """Script de PowerShell que sustituye el EXE y, si se indica ``state_dir``, lo verifica.

    Con verificación: tras lanzar el nuevo EXE espera hasta 45 s a que escriba
    ``State/launcher_ok.json`` con su versión. Si no aparece (el EXE no arranca o se cierra),
    lo detiene, restaura el anterior, lo vuelve a abrir y apunta la versión como fallida.
    """
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$LauncherPid = {int(pid)}",
        f"$Target = {quote(target)}",
        f"$Source = {quote(source)}",
        "$Backup = $Target + '.previous'",
    ]
    verify = version is not None and state_dir is not None
    if verify:
        lines += [
            f"$Marker = {quote(Path(state_dir) / OK_MARKER)}",
            f"$FailedFile = {quote(Path(state_dir) / FAILED_FILE)}",
            f"$ExpectedVersion = {quote(version)}",
        ]
    lines += [
        "Wait-Process -Id $LauncherPid -ErrorAction SilentlyContinue",
        "Start-Sleep -Milliseconds 700",
        "if (Test-Path -LiteralPath $Backup) { Remove-Item -LiteralPath $Backup -Force }",
        "if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $Backup -Force }",
        "try {",
        "  Move-Item -LiteralPath $Source -Destination $Target -Force",
    ]
    if verify:
        lines += [
            "  if (Test-Path -LiteralPath $Marker) { Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue }",
            "  $Proc = Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target) -PassThru",
            "  $Healthy = $false",
            f"  $Deadline = (Get-Date).AddSeconds({HANDSHAKE_SECONDS})",
            "  while ((Get-Date) -lt $Deadline) {",
            "    if (Test-Path -LiteralPath $Marker) {",
            "      try { $Info = Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json; if ($Info.version -eq $ExpectedVersion) { $Healthy = $true; break } } catch { }",
            "    }",
            "    if ($Proc.HasExited) { Start-Sleep -Milliseconds 500; if (Test-Path -LiteralPath $Marker) { $Healthy = $true }; break }",
            "    Start-Sleep -Milliseconds 400",
            "  }",
            "  if (-not $Healthy) {",
            "    Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue",
            "    Start-Sleep -Milliseconds 700",
            "    Add-Content -LiteralPath $FailedFile -Value $ExpectedVersion -Encoding UTF8",
            "    Remove-Item -LiteralPath $Target -Force -ErrorAction SilentlyContinue",
            "    Move-Item -LiteralPath $Backup -Destination $Target -Force",
            "    Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target)",
            "    throw 'El nuevo launcher no arrancó; se restauró el anterior.'",
            "  }",
            "  Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue",
        ]
    else:
        lines += [
            "  Start-Process -FilePath $Target -WorkingDirectory (Split-Path -Parent $Target)",
            "  Remove-Item -LiteralPath $Backup -Force -ErrorAction SilentlyContinue",
        ]
    lines += [
        "} catch {",
        "  if ((Test-Path -LiteralPath $Backup) -and -not (Test-Path -LiteralPath $Target)) { Move-Item -LiteralPath $Backup -Destination $Target -Force }",
        "  throw",
        "}",
        "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
        "",
    ]
    return "\n".join(lines)


def schedule_update(paths: AppPaths, update: LauncherUpdate, *, pid: int | None = None) -> Path:
    if not IS_WINDOWS:
        raise ValidationError("La autoactualización del launcher requiere Windows")
    target = launcher_install_path(paths)
    if not target.is_file():
        raise ValidationError("No se encontró el launcher instalado")
    temp_root = Path(tempfile.gettempdir()) / "FutonHUB-Launcher-Update"
    temp_root.mkdir(parents=True, exist_ok=True)
    script = temp_root / f"replace-{int(pid or os.getpid())}.ps1"
    script.write_text(
        build_replacement_script(
            target,
            update.downloaded_exe,
            pid=int(pid or os.getpid()),
            version=update.release.version,
            state_dir=paths.state,
        ),
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
