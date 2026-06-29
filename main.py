from __future__ import annotations

import sys

from futonhub_auto.bootstrap import ensure_launcher_installed
from futonhub_auto.config import LauncherConfig
from futonhub_auto.credentials import WindowsCredentialStore
from futonhub_auto.gui import run
from futonhub_auto.paths import AppPaths
from futonhub_auto.uninstall import run_uninstall_prompt


if __name__ == "__main__":
    paths = AppPaths.default()
    paths.ensure()
    if "--uninstall" in sys.argv[1:]:
        config = LauncherConfig.load_or_create(paths.config / "launcher.json")
        confirmed = run_uninstall_prompt(
            paths,
            WindowsCredentialStore(),
            config.credential_target,
        )
        raise SystemExit(0 if confirmed else 1)
    if not ensure_launcher_installed(paths):
        run()
