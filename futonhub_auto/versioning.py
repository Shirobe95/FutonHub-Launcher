from __future__ import annotations

import re


_VERSION_RE = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+].*)?$", re.ASCII)
_STRICT_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$", re.ASCII)
LAUNCHER_TAG_PREFIX = "launcher-v"


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch((value or "").strip())
    if not match:
        raise ValueError(f"Versión inválida: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def parse_release_tag(tag: str, prefix: str = LAUNCHER_TAG_PREFIX) -> str | None:
    """Devuelve ``X.Y.Z`` para tags ``launcher-vX.Y.Z`` estables; ``None`` si no aplica.

    Los tags con sufijo (``-rc1``, ``+meta``) no se consideran versiones estables.
    """
    if not tag.startswith(prefix):
        return None
    version = tag[len(prefix):]
    return version if _STRICT_RE.fullmatch(version) else None


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)
