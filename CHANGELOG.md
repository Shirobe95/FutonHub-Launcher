# Changelog

## 0.12.0

- Separate ERP updates from launcher updates.
- Read ERP commits from the private `FutonEspaiHUB` repository.
- Read launcher releases from the public `FutonHub-Launcher` repository.
- Never send the private ERP token to the public launcher repository.
- Add Windows CI and one-click GitHub Release publishing.
- Keep transactional replacement, SHA-256 validation, uninstall, diagnostics,
  Tcl/Tk isolation, rollback, and local data preservation.
