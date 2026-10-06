# Architecture

## ERP channel

- Repository: `Shirobe95/FutonEspaiHUB`
- Branch: `main`
- Private access: fine-grained token with `Contents: Read-only`
- Update identity: exact commit SHA

## Launcher channel

- Repository: `Shirobe95/FutonHub-Launcher`
- Public releases: `launcher-vX.Y.Z`
- Required assets: `FutonHUB-Launcher.exe` and
  `FutonHUB-Launcher.exe.sha256`
- No ERP token is sent when checking launcher releases.

The launcher checks its own public release channel first and then checks the
ERP branch. Both update paths retain SHA-256 validation and transactional
replacement.

## FutonHUB semantic version

The visible ERP version is read from package files, while commit SHA remains the update authority.
