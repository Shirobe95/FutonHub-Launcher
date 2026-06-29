from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from .errors import ValidationError


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
        for info in infos:
            pure = PurePosixPath(info.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValidationError(f"Ruta insegura en ZIP: {info.filename}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValidationError(
                    f"Enlace simbólico no permitido: {info.filename}"
                )
            target = (destination / Path(*pure.parts)).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise ValidationError(
                    f"Ruta fuera de staging: {info.filename}"
                ) from exc
        archive.extractall(destination)
    children = [item for item in destination.iterdir() if item.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination
