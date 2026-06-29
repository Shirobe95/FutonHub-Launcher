from __future__ import annotations

import re


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch((value or "").strip())
    if not match:
        raise ValueError(f"Versión inválida: {value!r}")
    return tuple(int(part) for part in match.groups())


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)
