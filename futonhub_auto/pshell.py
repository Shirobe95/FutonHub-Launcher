"""Utilidades para generar scripts de PowerShell de forma segura."""
from __future__ import annotations

# PowerShell trata como comillas simples: ' ‘ ’ ‚ ‛ (U+0027, U+2018-201B).
_SINGLE_QUOTES = ("'", "‘", "’", "‚", "‛")


def quote(value: object) -> str:
    """Literal de cadena entre comillas simples con todas las comillas escapadas."""
    text = str(value)
    for char in _SINGLE_QUOTES:
        text = text.replace(char, char * 2)
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError("Valor no permitido en un script de PowerShell")
    return "'" + text + "'"
