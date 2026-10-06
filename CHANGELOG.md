# Changelog

## 0.13.0 (rama test/upgrade-001, sin publicar)

Canal de pruebas (esta rama compila `CHANNEL_NAME = "test"`, ver `futonhub_auto/channel.py`):

- Sigue la rama `test/upgrade-001` del ERP, no la de producción.
- Se instala aparte (`%LOCALAPPDATA%\\FutonHUB-Test`), con su propio token (reutiliza el del
  launcher estable si existe, solo lectura), accesos directos «FutonHUB (Test)», entrada de
  desinstalación propia y distintivo TEST en la ventana. Puede convivir con el launcher real.
- Se autoactualiza solo con releases `launcher-test-vX.Y.Z` (prerelease). Los launchers estables
  ignoran esos tags, y este ignora los estables. `release-test.yml` publica uno por push a la rama.
- Autoactualización con verificación: el script espera a que el EXE nuevo confirme que arrancó
  (`State/launcher_ok.json`); si no, restaura el anterior, lo reabre y marca esa versión como
  fallida para no reintentarla. `--selftest` permite al CI probar el EXE compilado antes de publicar.
- Primera instalación sin ERP: se instala sola; si el Python del sistema no tiene tkinter/venv
  o falla la validación, usa el Python administrado en vez de dar error.

Funcional:

- GitHub: errores diferenciados (token 401, permisos 403, límite de uso 403/429, recurso 404,
  caídas 5xx/red). Reintentos con espera para fallos transitorios. El token se limpia
  (espacios, comillas, `Bearer`) y se valida antes de usarlo. `Authorization` ya no se reenvía
  en redirecciones a otro host.
- Si GitHub falla (token caducado, límite de uso, rama inexistente, sin red) y hay una versión
  instalada, **se abre esa versión** y se explica el motivo; solo se pide un token nuevo cuando
  el problema es el token. Una actualización fallida conserva la versión anterior.
- La autoactualización del launcher se comprueba **antes** y no depende del token del ERP.
- `launcher.json`: los ajustes de despliegue (rama, repos, Python e instalador) los manda
  siempre el código del launcher; solo se conservan `auto_open_erp`, `self_update_enabled` y
  `backup_retention` (validados). JSON dañado: se guarda como `.corrupt-<fecha>` y se restaura.
  Para forzar un valor a mano existe la clave `overrides`.
- Una sola instancia del launcher y un bloqueo entre procesos para actualizar/recuperar.
- Nuevo: «Restaurar anterior…» (desde `Rollback/`, conserva `.env` y datos) y «Reanudar
  actualizaciones» (la restauración fija la versión hasta reanudar).
- `GestorWoo/exports|logs|backups|user_config` pasan a conservarse al actualizar.
- Entorno virtual indexado por hash de requisitos **y** versión de Python.
- Endurecimiento del ZIP (límites de tamaño/entradas/ratio, nombres inválidos en Windows),
  del `.sha256` (una línea, nombre correcto) y de la selección de releases (la versión
  mayor estable; se ignoran `-rc`/sufijos y dígitos Unicode).
- Scripts PowerShell: se escapan también las comillas tipográficas.
- Errores no controlados: se escriben en `Logs/launcher-crash.log` y se avisa al usuario.
- `release.yml`: versión validada y pasada por variable de entorno, comprobación de
  `version_info.txt` y del `.sha256` antes de publicar. `build_launcher.bat` no hace `pause` en CI.
- Tests: 51 -> 106; cobertura 43 % -> 60 %.

## 0.12.0

- Separate ERP updates from launcher updates.
- Read ERP commits from the private `FutonEspaiHUB` repository.
- Read launcher releases from the public `FutonHub-Launcher` repository.
- Never send the private ERP token to the public launcher repository.
- Add Windows CI and one-click GitHub Release publishing.
- Keep transactional replacement, SHA-256 validation, uninstall, diagnostics,
  Tcl/Tk isolation, rollback, and local data preservation.
