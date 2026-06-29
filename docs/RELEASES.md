# Publishing a launcher release

1. Update `LAUNCHER_VERSION` in `futonhub_auto/__init__.py`.
2. Update `assets/version_info.txt`.
3. Update `CHANGELOG.md`.
4. Push the changes to `main`.
5. Wait for the `CI` workflow to pass.
6. Open **Actions → Publish launcher release → Run workflow**.
7. Enter the exact version, for example `0.12.0`.

The workflow runs tests, builds the Windows EXE, creates the SHA-256 file and
publishes a GitHub Release tagged `launcher-v0.12.0`.

Do not upload executables to the `main` branch. GitHub Releases is the official
binary distribution channel.
