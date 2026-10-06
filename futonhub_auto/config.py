from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass
class LauncherConfig:
    owner: str = "Shirobe95"
    repository: str = "FutonEspaiHUB"
    branch: str = "main"
    credential_target: str = "FutonHUB/GitHubReadOnly"
    auto_open_erp: bool = True
    self_update_enabled: bool = True
    worker_mode: bool = True
    launcher_owner: str = "Shirobe95"
    launcher_repository: str = "FutonHub-Launcher"
    backup_retention: int = 3
    python_version: str = "3.13.14"
    python_installer_url: str = (
        "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe"
    )
    python_installer_sha256: str = (
        "c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0"
    )

    @classmethod
    def load_or_create(cls, path: Path) -> "LauncherConfig":
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            config = cls()
            config.save(path)
            return config
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Configuración inválida: {exc}") from exc
        allowed = set(cls.__dataclass_fields__)
        config = cls(**{key: value for key, value in raw.items() if key in allowed})
        if (
            config.owner == "Shirobe95"
            and config.repository == "FutonEspaiHUB"
            and config.branch == "refactor/modularizacion-v1"
        ):
            config.branch = "main"
            config.save(path)
        return config

    def save(self, path: Path) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
