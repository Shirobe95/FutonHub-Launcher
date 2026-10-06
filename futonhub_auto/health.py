"""Comprobaciones y informe técnico del launcher, independientes de Tk.

La pantalla de problemas muestra una línea por cosa que debía estar bien
(``Check``), con su mensaje en lenguaje llano y, si existe, el botón que lo
arregla. El informe técnico (``build_report``) es lo que el usuario copia y nos
envía; nunca incluye el token.
"""
from __future__ import annotations

from dataclasses import dataclass
import platform
from typing import Iterable

from .logging_utils import redact

OK, WARN, FAIL, UNKNOWN = "ok", "warn", "fail", "unknown"

# Acciones que la interfaz sabe ejecutar desde una línea del chequeo.
ACTION_TOKEN = "token"
ACTION_ENV = "env"
ACTION_RETRY = "retry"
ACTION_LOGS = "logs"


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str
    message: str = ""
    action: str | None = None
    action_label: str = ""


def build_checks(
    kind: str | None,
    *,
    installation_ready: bool,
    env_present: bool,
    installed_version: str = "",
    detail: str = "",
) -> list[Check]:
    """Lista de comprobaciones a mostrar según el tipo de fallo (``FailureDecision.kind``).

    ``kind`` puede ser: token, no_token, not_found, rate_limit, network, update_failed,
    busy, unexpected, erp_crash o None (sin fallo conocido).
    """
    network = Check("network", "Conexión a Internet", UNKNOWN, "Sin comprobar")
    github = Check("github", "Acceso a GitHub", UNKNOWN, "Sin comprobar")
    update = Check("update", "Actualización de FutonHUB", UNKNOWN, "Sin comprobar")

    if kind == "network":
        network = Check("network", network.label, FAIL, "No hay conexión con GitHub. Revisa Internet y reintenta.", ACTION_RETRY, "Reintentar")
    else:
        network = Check("network", network.label, OK, "Correcta")
        if kind in ("token", "no_token"):
            message = (
                "Falta el acceso. Hay que introducir el token."
                if kind == "no_token"
                else "El token ha caducado o no tiene permisos."
            )
            github = Check("github", github.label, FAIL, message, ACTION_TOKEN, "Introducir token")
        elif kind == "rate_limit":
            github = Check("github", github.label, WARN, "GitHub limitó las consultas. Se resolverá solo en unos minutos.", ACTION_RETRY, "Reintentar")
        elif kind == "not_found":
            github = Check("github", github.label, FAIL, "No se encuentra la versión del ERP en GitHub. Avisa a soporte.")
        else:
            github = Check("github", github.label, OK, "Correcto")
            if kind == "update_failed":
                update = Check("update", update.label, FAIL, "No se pudo instalar la nueva versión. Se mantiene la anterior.", ACTION_RETRY, "Reintentar")
            elif kind in ("unexpected", "busy"):
                update = Check("update", update.label, FAIL, detail or "Error inesperado.", ACTION_LOGS, "")
            elif kind is None:
                update = Check("update", update.label, OK, "Al día")

    erp_label = "FutonHUB instalado"
    if kind == "erp_crash":
        erp = Check("erp", erp_label, FAIL, detail or "FutonHUB se cerró con un error.")
    elif installation_ready:
        erp = Check("erp", erp_label, OK, f"Versión {installed_version}" if installed_version else "Correcto")
    else:
        erp = Check("erp", erp_label, FAIL, "Todavía no está instalado.")

    if env_present:
        env = Check("env", "Archivo .env", OK, "Encontrado")
    else:
        env = Check("env", "Archivo .env", WARN, "No encontrado. Selecciónalo para poder abrir FutonHUB.", ACTION_ENV, "Seleccionar…")

    return [network, github, update, erp, env]


def problem_headline(kind: str | None, installation_ready: bool) -> tuple[str, str]:
    """Titular y subtítulo sencillos para la pantalla de problemas."""
    if kind == "erp_crash":
        return "FutonHUB se cerró con un error", "Copia el informe técnico y envíaselo a soporte."
    if kind == "busy":
        return "El launcher ya está abierto", "Cierra la otra ventana antes de continuar."
    if installation_ready:
        return "Puedes abrir FutonHUB", "No se pudo comprobar si hay actualizaciones."
    return "No se pudo preparar FutonHUB", "Revisa los puntos marcados; si sigue igual, copia el informe y envíalo a soporte."


def worst_status(checks: Iterable[Check]) -> str:
    statuses = {check.status for check in checks}
    return FAIL if FAIL in statuses else WARN if WARN in statuses else OK


def build_report(
    *,
    launcher_version: str,
    channel: str,
    title: str,
    kind: str | None,
    message: str,
    status_text: str,
    installed: str,
    available: str,
    checks: Iterable[Check],
    activity: Iterable[str],
    extra: str = "",
    secret: str | None = None,
) -> str:
    """Informe técnico para soporte. Se redacta cualquier rastro del token."""
    lines = [
        "INFORME TÉCNICO · FutonHUB Launcher",
        f"Launcher: v{launcher_version} [{channel}]",
        f"Sistema: {platform.system()} {platform.release()} · Python {platform.python_version()}",
        f"Resumen: {title}",
        f"Tipo de fallo: {kind or 'ninguno'}",
        f"Mensaje: {message}",
        f"Estado: {status_text}",
        f"FutonHUB instalado: {installed}",
        f"FutonHUB disponible: {available}",
        "",
        "Comprobaciones:",
    ]
    for check in checks:
        lines.append(f"  [{check.status.upper():7}] {check.label}: {check.message}")
    if extra.strip():
        lines += ["", "Detalle:", extra.strip()]
    recent = list(activity)[-60:]
    if recent:
        lines += ["", "Actividad reciente:", *("  " + item for item in recent)]
    return redact("\n".join(lines), secret)
