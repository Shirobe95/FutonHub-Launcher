# LAUNCH-013 · Resultados

## 1. Causa del comportamiento actual

La interfaz utilizaba directamente `SOURCE_COMMIT` y el SHA resuelto de GitHub
como valores de las dos tarjetas principales. No existía una capa que leyera la
versión SemVer declarada por FutonHUB.

## 2. Fuente local elegida

Orden real de resolución:

1. `GestorWoo/pyproject.toml` → `[project].version`.
2. `GestorWoo/src/futonhub/__init__.py` → `__version__`.
3. `GestorWoo/src/gestorwoo/__init__.py` → `__version__`.
4. Tag SemVer exacto del commit instalado, cuando GitHub está disponible.
5. `Desconocida`, manteniendo el commit en logs.

La versión persistida en `SOURCE_INFO.json` y `VERSION` es auxiliar. Los archivos
del paquete instalado siguen siendo la fuente de verdad.

## 3. Fuente remota elegida

El cliente GitHub existente consulta los mismos tres archivos en el commit exacto
resuelto desde `main`. Usar el SHA como `ref` evita mezclar la versión de un commit
con el snapshot de otro si la rama cambia durante la operación. Como compatibilidad
final se consulta un tag SemVer exacto del commit.

## 4. Archivos modificados

- `futonhub_auto/versioning.py`
- `futonhub_auto/github_api.py`
- `futonhub_auto/gui.py`
- `futonhub_auto/config.py`
- `futonhub_auto/deployment.py`
- `futonhub_auto/transaction.py`
- `futonhub_auto/__init__.py`
- `assets/version_info.txt`
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `README.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/RELEASES.md`
- pruebas existentes y `tests/test_futonhub_versioning.py`

## 5. Cambios de interfaz

Las tarjetas pasan de:

```text
Commit instalado | Commit remoto
```

a:

```text
Versión instalada | Versión disponible
```

Los valores se normalizan visualmente con prefijo `v`. La cabecera conserva la
versión independiente del Launcher.

## 6. Fallbacks y errores

- Archivos inexistentes, TOML malformado, Python inválido y versiones vacías no
  bloquean el Launcher.
- Si existe commit pero no se resuelve SemVer, se muestra `Desconocida`.
- Los detalles se registran como diagnóstico de versión sin traceback visible.
- Las instalaciones antiguas que solo guardan el commit siguen siendo válidas.
- La rama histórica `refactor/modularizacion-v1` se migra a `main` en la
  configuración estándar de FutonHUB.

## 7. Autoridad de actualización

La regla no cambia:

```text
commit instalado != commit remoto → actualización disponible
```

La versión SemVer nunca decide por sí sola. Si las versiones coinciden y los
commits no, la actualización continúa y se registra una advertencia técnica.

## 8. Tests añadidos

Se añadieron pruebas para lectura TOML, normalización visual, ambos fallbacks
Python, ausencia de archivos, TOML dañado, versión vacía, estados 0.2.1→0.3.0,
estado actualizado, misma versión con commits distintos, versiones desconocidas,
refresco posterior a actualización, autoridad del commit, hashes completos en
log, excepciones no bloqueantes, lectura remota por SHA, fallback por tag,
metadatos auxiliares, títulos de interfaz, migración de rama y persistencia
SemVer durante el despliegue.

## 9. Resultados exactos

```text
73 tests OK
compileall OK
```

El `GestorWoo/pyproject.toml` remoto de `main` fue comprobado y declara `0.3.0`.
El commit remoto comprobado es `2b2eee8e1dfd976c5fa8d2e150d76938f1639990`.

## 10. Versión final del Launcher

```text
0.13.0
```

Se actualizaron `LAUNCHER_VERSION` y los metadatos Windows del EXE.

## 11. Smoke manual

Pendiente en Windows. La suite y la compilación Python están aprobadas, pero el
EXE todavía debe construirse mediante CI y probarse con una instalación real
0.2.1 → 0.3.0.

## 12. Git

No se ejecutaron comandos Git, no se creó commit, no se creó tag y no se hizo
push durante este corte.
