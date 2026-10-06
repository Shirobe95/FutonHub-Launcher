"""Canal de distribución del launcher.

``stable`` es el launcher que usan los PCs de Futon Espai (rama ``refactor/modularizacion-v1``).
``test`` es el launcher de pruebas: apunta a la rama ``test/upgrade-001`` del ERP, se instala
en una carpeta distinta, tiene su propio token, accesos directos y entrada de desinstalación,
y solo se autoactualiza con releases ``launcher-test-vX.Y.Z``. Así nunca pisa la instalación
real ni recibe/envía actualizaciones del canal estable.

CHANNEL es una constante de compilación: promover una versión a estable = cambiarla a
``"stable"`` en una revisión explícita (los workflows comprueban que coincide con el canal).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    name: str
    app_dir_name: str
    display_name: str
    shortcut_name: str
    registry_key: str
    erp_branch: str
    credential_target: str
    release_tag_prefix: str
    allow_prerelease: bool
    window_badge: str


CHANNELS = {
    "stable": Channel(
        name="stable",
        app_dir_name="FutonHUB",
        display_name="FutonHUB",
        shortcut_name="FutonHUB",
        registry_key="FutonHUB",
        erp_branch="refactor/modularizacion-v1",
        credential_target="FutonHUB/GitHubReadOnly",
        release_tag_prefix="launcher-v",
        allow_prerelease=False,
        window_badge="",
    ),
    "test": Channel(
        name="test",
        app_dir_name="FutonHUB-Test",
        display_name="FutonHUB (Test)",
        shortcut_name="FutonHUB (Test)",
        registry_key="FutonHUB-Test",
        erp_branch="test/upgrade-001",
        credential_target="FutonHUB-Test/GitHubReadOnly",
        release_tag_prefix="launcher-test-v",
        allow_prerelease=True,
        window_badge="TEST",
    ),
}

CHANNEL_NAME = "test"
CHANNEL = CHANNELS[CHANNEL_NAME]
STABLE = CHANNELS["stable"]
