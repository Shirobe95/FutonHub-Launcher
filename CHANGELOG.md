# Changelog

## 0.14.1 (canal test)

Une el launcher 0.14.0 (diseño compacto para trabajadores, versión semántica del ERP, popups copiables) con la
rama de correcciones funcionales 0.13.x. El diseño de 0.14.0 se conserva tal cual; la lógica nueva es la de 0.13.x:
errores de GitHub diferenciados, abrir la versión instalada si falla GitHub, instancia única, autoactualización
con reversión, restaurar versión anterior, `launcher.json` validado, canal de pruebas aislado, etc.

## 0.14.0

- Rediseño compacto orientado a trabajadores.
- Panel de administración oculto por defecto y accesible con Ctrl+Shift+A.
- Logo visual FutonEspai en cabecera.
- Detalles técnicos plegables para no saturar la interfaz.
- Popups visuales de error con mensaje copiable para soporte.
- Aviso visual cuando falla la comprobación o descarga de actualización del launcher.
- Se mantiene la actualización automática del launcher desde GitHub Releases con SHA-256 y reemplazo transaccional.

## 0.14.0

- Show FutonHUB semantic versions instead of commit hashes in the main UI.
- Read the installed version from `GestorWoo/pyproject.toml` with Python package fallbacks.
- Read the remote version from the exact commit resolved from `main`.
- Keep commit SHA as the only update decision rule.
- Preserve full commit hashes in activity logs and audit metadata.
- Migrate legacy ERP branch configuration to `main`.

## 0.13.3 (canal test)

- Se eliminan las constantes locales: `CalculoCoste/constantes_negocio.json` ya no se protege entre
  actualizaciones ni lo comprueba el health check. Las constantes viven solo en Supabase.

## 0.13.2 (canal test)

- Health check: `CalculoCoste/constantes_negocio.json` pasa a ser opcional. Supabase es la fuente de verdad de
  las constantes y ese JSON es solo una cache local que el ERP regenera; si falta (instalación nueva) ya no
  bloquea la instalación. Si existe pero está corrupto, sigue bloqueando.

## 0.13.1 (canal test: PALIKO visual)

Incluye todo lo de 0.13.0 (canal de pruebas, lógica funcional) más la capa visual.

## 0.13.0 (rama test/upgrade-001)

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

Visual (sistema PALIKO, `futonhub_auto/theme.py`):

- Tema oscuro grafito/azulado con acento cian, paneles planos de 1 px, tipografía del sistema
  (Segoe UI en Windows) y barra de título oscura en Windows 10/11.
- Estado principal con indicador de color (trabajando / listo / avisos / detenido), barra de
  progreso, commits instalado y remoto (datos reales), actividad con niveles por color, una
  acción principal («Abrir FutonHUB») y el resto en secundarias y en «Más».
- Tests de humo de la GUI (se omiten si no hay pantalla).

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
