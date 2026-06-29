from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    app: Path
    staging: Path
    rollback: Path
    state: Path
    downloads: Path
    config: Path
    logs: Path
    runtime: Path

    @classmethod
    def default(cls) -> "AppPaths":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return cls.from_root(base / "FutonHUB")

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        root = root.expanduser().resolve()
        return cls(
            root=root,
            app=root / "App",
            staging=root / "Staging",
            rollback=root / "Rollback",
            state=root / "State",
            downloads=root / "Downloads",
            config=root / "Config",
            logs=root / "Logs",
            runtime=root / "Runtime",
        )

    def ensure(self) -> None:
        for path in (
            self.root,
            self.staging,
            self.rollback,
            self.state,
            self.downloads,
            self.config,
            self.logs,
            self.runtime,
        ):
            path.mkdir(parents=True, exist_ok=True)
