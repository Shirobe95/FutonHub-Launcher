# Publishing a launcher release

1. Update `LAUNCHER_VERSION` in `futonhub_auto/__init__.py`.
2. Update `assets/version_info.txt`.
3. Update `CHANGELOG.md`.
4. Push the changes to `main`.
5. Wait for the `CI Launcher` workflow to pass.
6. Open **Actions → Publish launcher release → Run workflow**.
7. Enter the exact version, for example `0.14.0`.

The workflow runs tests, builds the Windows EXE, creates the SHA-256 file and
publishes a GitHub Release tagged `launcher-v0.14.0`.

Do not upload executables to the `main` branch. GitHub Releases is the official
binary distribution channel.


## Canal de pruebas

La rama `test/upgrade-001` compila el canal `test` (`futonhub_auto/channel.py`). Cada push publica
un **prerelease** `launcher-test-vX.Y.Z` (hay que subir `LAUNCHER_VERSION`; si el tag existe se omite).
El canal estable (`release.yml`, tags `launcher-vX.Y.Z`) exige `CHANNEL_NAME = "stable"`.
Promover una versión a estable es un cambio explícito de esa constante, nunca un merge accidental.
