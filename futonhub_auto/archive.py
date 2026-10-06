from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

from .errors import ValidationError

MAX_ENTRIES = 50_000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024  # 1 GiB descomprimido
MAX_RATIO = 200  # ratio de compresión máximo por archivo
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _check_name(filename: str) -> PurePosixPath:
    if "\\" in filename:
        raise ValidationError(f"Ruta insegura en ZIP (barra invertida): {filename}")
    pure = PurePosixPath(filename)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValidationError(f"Ruta insegura en ZIP: {filename}")
    for part in pure.parts:
        if _BAD_CHARS.search(part):
            raise ValidationError(f"Nombre no válido en Windows dentro del ZIP: {filename}")
        if part != part.rstrip(" .") or part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise ValidationError(f"Nombre reservado o no válido en Windows dentro del ZIP: {filename}")
    return pure


def safe_extract_snapshot(zip_path: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    try:
        archive_handle = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ValidationError("El snapshot descargado no es un ZIP válido") from exc
    with archive_handle as archive:
        infos = archive.infolist()
        if not infos:
            raise ValidationError("El ZIP de GitHub está vacío")
        if len(infos) > MAX_ENTRIES:
            raise ValidationError(f"El ZIP tiene demasiados archivos ({len(infos)})")
        total = 0
        root = destination.resolve()
        for info in infos:
            pure = _check_name(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValidationError(
                    f"Enlace simbólico no permitido: {info.filename}"
                )
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValidationError("El ZIP descomprimido supera el tamaño máximo permitido")
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 10 * 1024 * 1024:
                raise ValidationError(f"Ratio de compresión sospechoso en {info.filename}")
            target = (destination / Path(*pure.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValidationError(
                    f"Ruta fuera de staging: {info.filename}"
                ) from exc
        archive.extractall(destination)
    children = [item for item in destination.iterdir() if item.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination
