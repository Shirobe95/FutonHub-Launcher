from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from .errors import ValidationError


PROTECTED_PATHS = (
    "GestorWoo/.env",
    "GestorWoo/data",
    "CalculoCoste/constantes_negocio.json",
    "CalculoCoste/data.xlsx",
    "logs",
    "backups",
    "exports",
    "user_config",
    "launcher_config.json",
)

EXCLUDED_DIRS = {
    ".git",
    ".codex",
    ".agents",
    ".pytest_cache",
    "__pycache__",
    "tests",
    "docs",
    "scripts",
    "auditoria",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
}


@dataclass(frozen=True)
class DeploymentResult:
    files: int
    commit: str


MANAGED_ENTRYPOINT = r'''@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FutonHUB ERP
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "RUNTIME_FILE=%~dp0runtime_python.txt"
if not exist "%RUNTIME_FILE%" exit /b 2
set "PYTHON_EXE="
for /f "usebackq delims=" %%I in ("%RUNTIME_FILE%") do set "PYTHON_EXE=%%I"
if not defined PYTHON_EXE exit /b 2
if not exist "%PYTHON_EXE%" exit /b 3
if not exist "%~dp0GestorWoo\gestorwoo.py" exit /b 4
pushd "%~dp0GestorWoo"
"%PYTHON_EXE%" gestorwoo.py erp-prototype
set "APP_EXIT=%ERRORLEVEL%"
popd
if /I "%FUTONHUB_LAUNCHER%"=="1" exit /b %APP_EXIT%
echo.
echo FutonHUB se ha cerrado. Codigo: %APP_EXIT%
pause
exit /b %APP_EXIT%
'''


HEALTH_CHECK = r'''from __future__ import annotations
import importlib
import json
from pathlib import Path
import sqlite3
import sys


def main() -> int:
    root = Path(__file__).resolve().parent
    checks = []

    def add(name, ok, detail="", blocking=True):
        checks.append({
            "name": name,
            "ok": bool(ok),
            "detail": detail,
            "blocking": blocking,
        })

    add("python", sys.version_info >= (3, 11), sys.version.split()[0])
    for relative in [
        "Abrir ERP.bat",
        "GestorWoo/gestorwoo.py",
        "GestorWoo/src/futonhub/app/cli.py",
        "GestorWoo/src/futonhub/ui/erp/prototype.py",
        "CalculoCoste/coste_pedido.py",
        "SOURCE_COMMIT",
    ]:
        add("required:" + relative, (root / relative).is_file())

    sys.path.insert(0, str(root / "GestorWoo/src"))
    for module in [
        "tkinter",
        "futonhub.app.cli",
        "futonhub.ui.erp.prototype",
        "dotenv",
        "requests",
        "pandas",
        "openpyxl",
        "PIL",
        "reportlab",
        "supabase",
    ]:
        try:
            importlib.import_module(module)
        except Exception as exc:
            add("import:" + module, False, f"{type(exc).__name__}: {exc}")
        else:
            add("import:" + module, True)

    constants = root / "CalculoCoste/constantes_negocio.json"
    if constants.exists():
        try:
            json.loads(constants.read_text(encoding="utf-8"))
        except Exception as exc:
            add("constants_json", False, str(exc))
        else:
            add("constants_json", True)
    else:
        add("constants_json", False, "ausente")

    database = root / "GestorWoo/data/gestorwoo.sqlite3"
    if database.exists():
        try:
            connection = sqlite3.connect(
                f"file:{database.as_posix()}?mode=ro",
                uri=True,
                timeout=3,
            )
            connection.execute("PRAGMA schema_version").fetchone()
            connection.close()
        except Exception as exc:
            add("sqlite_read_only", False, str(exc))
        else:
            add("sqlite_read_only", True)

    env_exists = (root / "GestorWoo/.env").is_file() or (root / ".env").is_file()
    add(
        "env_present",
        env_exists,
        "presente" if env_exists else "ausente",
        blocking=False,
    )

    failed = [check for check in checks if not check["ok"] and check["blocking"]]
    warnings = [
        check for check in checks if not check["ok"] and not check["blocking"]
    ]
    print(json.dumps({"ok": not failed, "checks": checks, "warnings": warnings}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _excluded(relative: Path) -> bool:
    return (
        any(part in EXCLUDED_DIRS for part in relative.parts)
        or relative.suffix.lower() in EXCLUDED_SUFFIXES
        or relative.name == ".env"
    )


def _copy_filtered(source: Path, destination: Path) -> int:
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if _excluded(relative):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def validate_snapshot(root: Path) -> None:
    required = [
        root / "GestorWoo/gestorwoo.py",
        root / "GestorWoo/src/futonhub/app/cli.py",
        root / "GestorWoo/src/futonhub/ui/erp/prototype.py",
        root / "CalculoCoste/coste_pedido.py",
        root / "requirements_erp.txt",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise ValidationError("Snapshot incompleto: " + ", ".join(missing))


def refresh_managed_files(destination: Path) -> bool:
    """Refresh launcher-owned support files without touching ERP source/data."""
    changed = False
    expected = {
        destination / "Abrir ERP.bat": (MANAGED_ENTRYPOINT, "ascii", "\r\n"),
        destination / "health_check.py": (HEALTH_CHECK, "utf-8", "\n"),
    }
    for path, (content, encoding, newline) in expected.items():
        current = None
        if path.is_file():
            try:
                current = path.read_text(encoding=encoding)
            except (OSError, UnicodeError):
                current = None
        normalized = content.replace("\r\n", "\n")
        if current is None or current.replace("\r\n", "\n") != normalized:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding, newline=newline)
            changed = True
    return changed


def create_runtime(
    snapshot: Path,
    destination: Path,
    *,
    commit: str,
    repository: str,
    branch: str,
    commit_date: str,
    archive_sha256: str,
) -> DeploymentResult:
    validate_snapshot(snapshot)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    copied = 0
    for relative in ("GestorWoo", "CalculoCoste"):
        source = snapshot / relative
        if source.is_dir():
            copied += _copy_filtered(source, destination / relative)
    shutil.copy2(snapshot / "requirements_erp.txt", destination / "requirements_erp.txt")
    copied += 1
    refresh_managed_files(destination)
    (destination / "SOURCE_COMMIT").write_text(commit + "\n", encoding="ascii")
    (destination / "VERSION").write_text(
        f"0.0.0+git.{commit[:12]}\n",
        encoding="ascii",
    )
    (destination / "SOURCE_INFO.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "branch": branch,
                "commit": commit,
                "commit_date": commit_date,
                "archive_sha256": archive_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return DeploymentResult(copied + 5, commit)


def preserve_existing(current: Path, staged: Path) -> list[str]:
    preserved: list[str] = []
    if not current.is_dir():
        return preserved
    for relative in PROTECTED_PATHS:
        source = current / relative
        if not source.exists():
            continue
        target = staged / relative
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        preserved.append(relative)
    return preserved
