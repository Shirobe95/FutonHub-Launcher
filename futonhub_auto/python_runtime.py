from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import LauncherConfig
from .errors import DownloadError, ValidationError


Status = Callable[[str], None]
Progress = Callable[[int, int | None], None]
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class RuntimeResult:
    python: Path
    requirements_hash: str
    created: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    cwd: Path,
    timeout: int,
    prefix: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"{prefix}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "sin detalle").strip()
        raise ValidationError(f"{prefix}: {detail[-4000:]}")
    return result


def _valid_python(command: Sequence[str]) -> Path | None:
    try:
        result = subprocess.run(
            [
                *command,
                "-c",
                (
                    "import sys;print(sys.executable);"
                    "raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    values = (result.stdout or "").strip().splitlines()
    return Path(values[-1]).resolve() if values else None


def detect_python(runtime_root: Path) -> Path | None:
    managed = runtime_root / "Python313/python.exe"
    candidates: list[tuple[str, ...]] = []
    if managed.is_file():
        candidates.append((str(managed),))
    if not getattr(sys, "frozen", False):
        candidates.append((sys.executable,))
    candidates.extend(
        (
            ("py", "-3"),
            ("python",),
            ("python3",),
        )
    )
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        found = _valid_python(candidate)
        if found:
            return found
    return None


def install_managed_python(
    runtime_root: Path,
    config: LauncherConfig,
    status: Status,
    progress: Progress,
) -> Path:
    if os.name != "nt":
        raise ValidationError(
            "La instalación automática de Python está diseñada para Windows"
        )
    installers = runtime_root / "Installers"
    installers.mkdir(parents=True, exist_ok=True)
    installer = installers / f"python-{config.python_version}-amd64.exe"
    valid_cached = (
        installer.is_file()
        and sha256_file(installer).lower()
        == config.python_installer_sha256.lower()
    )
    if not valid_cached:
        installer.unlink(missing_ok=True)
        status(f"Descargando Python {config.python_version} desde python.org…")
        request = Request(
            config.python_installer_url,
            headers={"User-Agent": "FutonHUB-AutoLauncher/0.10"},
        )
        written = 0
        try:
            with urlopen(request, timeout=180) as response, installer.open(
                "wb"
            ) as handle:
                total_header = response.headers.get("Content-Length")
                total = (
                    int(total_header)
                    if total_header and total_header.isdigit()
                    else None
                )
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    progress(written, total)
        except (OSError, URLError) as exc:
            installer.unlink(missing_ok=True)
            raise DownloadError(f"No se pudo descargar Python: {exc}") from exc
        actual = sha256_file(installer)
        if actual.lower() != config.python_installer_sha256.lower():
            installer.unlink(missing_ok=True)
            raise ValidationError(
                "El instalador de Python no coincide con el SHA-256 oficial"
            )

    target = runtime_root / "Python313"
    target.mkdir(parents=True, exist_ok=True)
    status("Instalando Python de forma silenciosa…")
    arguments = [
        str(installer),
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_pip=1",
        "Include_test=0",
        "Include_launcher=0",
        f"TargetDir={target}",
    ]
    _run(arguments, runtime_root, 900, "No se pudo instalar Python")
    python = target / "python.exe"
    if not python.is_file():
        raise ValidationError(
            "Python no quedó instalado en la ruta administrada"
        )
    return python


def ensure_base_python(
    runtime_root: Path,
    config: LauncherConfig,
    status: Status,
    progress: Progress,
) -> Path:
    found = detect_python(runtime_root)
    if found:
        return found
    return install_managed_python(runtime_root, config, status, progress)


def prepare_runtime(
    staged_app: Path,
    runtime_root: Path,
    base_python: Path,
    status: Status,
) -> RuntimeResult:
    requirements = staged_app / "requirements_erp.txt"
    if not requirements.is_file():
        raise ValidationError("La rama no contiene requirements_erp.txt")
    requirements_hash = sha256_file(requirements)
    venv_dir = runtime_root / "venvs" / requirements_hash[:16]
    python = (
        venv_dir / "Scripts/python.exe"
        if os.name == "nt"
        else venv_dir / "bin/python"
    )
    created = False
    if not python.is_file():
        status("Creando entorno aislado del ERP…")
        shutil.rmtree(venv_dir, ignore_errors=True)
        _run(
            [str(base_python), "-m", "venv", str(venv_dir)],
            staged_app,
            300,
            "No se pudo crear el entorno ERP",
        )
        created = True

    marker = venv_dir / ".requirements.json"
    marker_hash = ""
    if marker.is_file():
        try:
            marker_hash = str(
                json.loads(marker.read_text(encoding="utf-8")).get("sha256")
                or ""
            )
        except (OSError, json.JSONDecodeError):
            marker_hash = ""
    if marker_hash != requirements_hash:
        status("Instalando dependencias de FutonHUB…")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "-r",
                str(requirements),
            ],
            staged_app,
            2400,
            "No se pudieron instalar las dependencias",
        )
        marker.write_text(
            json.dumps({"sha256": requirements_hash}, indent=2) + "\n",
            encoding="utf-8",
        )
    (staged_app / "runtime_python.txt").write_text(
        str(python.resolve()) + "\n",
        encoding="utf-8",
    )
    return RuntimeResult(python.resolve(), requirements_hash, created)
