# Changelog

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

## 0.12.0

- Separate ERP updates from launcher updates.
- Read ERP commits from the private `FutonEspaiHUB` repository.
- Read launcher releases from the public `FutonHub-Launcher` repository.
- Never send the private ERP token to the public launcher repository.
- Add Windows CI and one-click GitHub Release publishing.
- Keep transactional replacement, SHA-256 validation, uninstall, diagnostics,
  Tcl/Tk isolation, rollback, and local data preservation.
