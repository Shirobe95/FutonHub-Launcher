# FutonHUB Launcher 0.12.0

Autonomous Windows launcher for installing, updating, validating and opening
FutonHUB.

## Update channels

- **ERP:** reads the exact commit from the private repository
  `Shirobe95/FutonEspaiHUB`, branch `refactor/modularizacion-v1`.
- **Launcher:** reads public GitHub Releases from
  `Shirobe95/FutonHub-Launcher`.

The private ERP token is stored in Windows Credential Manager and is never sent
to the public launcher repository.

## Local build

```text
run_tests.bat
build_launcher.bat
```

Artifacts:

```text
dist/FutonHUB-Launcher.exe
dist/FutonHUB-Launcher.exe.sha256
```

## Automated release

Push source changes to `main`, wait for CI, then run the
**Publish launcher release** workflow with the exact source version. The workflow
creates the GitHub Release and uploads both required assets.

See `docs/ARCHITECTURE.md`, `docs/RELEASES.md` and
`docs/GUIA_PC_NUEVO.md`.
