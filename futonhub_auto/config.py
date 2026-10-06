from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .channel import CHANNEL


CONFIG_SCHEMA = 2

# Ajustes que el usuario puede cambiar y que se conservan entre versiones.
USER_FIELDS = ("auto_open_erp", "self_update_enabled", "backup_retention")
# Ajustes de despliegue: SIEMPRE manda el código del launcher. Solo se pueden
# sobrescribir a mano con la clave ``overrides`` de launcher.json (diagnóstico).
MANAGED_FIELDS = (
    "owner",
    "repository",
    "branch",
    "credential_target",
    "launcher_owner",
    "launcher_repository",
    "python_version",
    "python_installer_url",
    "python_installer_sha256",
    "release_tag_prefix",
)


@dataclass
class LauncherConfig:
    owner: str = "Shirobe95"
    repository: str = "FutonEspaiHUB"
    branch: str = CHANNEL.erp_branch
    credential_target: str = CHANNEL.credential_target
    auto_open_erp: bool = True
    self_update_enabled: bool = True
    launcher_owner: str = "Shirobe95"
    launcher_repository: str = "FutonHub-Launcher"
    backup_retention: int = 3
    release_tag_prefix: str = CHANNEL.release_tag_prefix
    release_allow_prerelease: bool = CHANNEL.allow_prerelease
    python_version: str = "3.13.14"
    python_installer_url: str = (
        "https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe"
    )
    python_installer_sha256: str = (
        "c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0"
    )
    # Mensajes de la última carga (JSON corrupto recuperado, valores descartados…).
    notices: tuple[str, ...] = ()

    @classmethod
    def load_or_create(cls, path: Path) -> "LauncherConfig":
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            config = cls()
            config.save(path)
            return config
        notices: list[str] = []
        raw: Any
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("el JSON no es un objeto")
        except (OSError, ValueError) as exc:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            broken = path.with_name(f"{path.name}.corrupt-{stamp}")
            try:
                path.replace(broken)
                notices.append(
                    f"launcher.json estaba dañado ({exc}); se guardó como {broken.name} "
                    "y se restauró la configuración por defecto."
                )
            except OSError:
                notices.append(f"launcher.json estaba dañado ({exc}); se usa la configuración por defecto.")
            config = cls(notices=tuple(notices))
            config.save(path)
            return config

        config = cls()
        overrides = raw.get("overrides") if isinstance(raw.get("overrides"), dict) else {}
        for name in USER_FIELDS:
            if name in raw:
                value = raw[name]
                if name == "backup_retention":
                    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 20:
                        config.backup_retention = value
                    else:
                        notices.append(f"backup_retention={value!r} no es válido (1-20); se usa {config.backup_retention}.")
                elif isinstance(value, bool):
                    setattr(config, name, value)
                else:
                    notices.append(f"{name}={value!r} no es booleano; se usa el valor por defecto.")
        for name in MANAGED_FIELDS:
            if name in overrides and isinstance(overrides[name], str) and overrides[name].strip():
                setattr(config, name, overrides[name].strip())
                notices.append(f"Valor manual en overrides: {name}.")
        config.notices = tuple(notices)
        if raw.get("schema") != CONFIG_SCHEMA or notices:
            config.save(path, overrides=overrides)
        return config

    def save(self, path: Path, overrides: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"schema": CONFIG_SCHEMA}
        for name in USER_FIELDS:
            payload[name] = getattr(self, name)
        if overrides:
            payload["overrides"] = overrides
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


