from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from futonhub_auto.github_api import GitHubClient
from futonhub_auto.versioning import (
    FutonHUBVersionState,
    commits_require_update,
    display_version,
    fetch_remote_futonhub_version,
    read_installed_futonhub_version,
    read_persisted_futonhub_version,
)


class FakeRemoteClient:
    def __init__(self, files=None, tag=None, error: Exception | None = None):
        self.files = files or {}
        self.tag = tag
        self.error = error
        self.requests: list[tuple[str, str | None]] = []

    def fetch_text_file(self, path: str, *, ref: str | None = None) -> str:
        self.requests.append((path, ref))
        if self.error:
            raise self.error
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def exact_semver_tag(self, commit_sha: str) -> str | None:
        if self.error:
            raise self.error
        return self.tag


class FutonHUBVersioningTests(unittest.TestCase):
    def _root(self, temp: str) -> Path:
        return Path(temp)

    def _write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_reads_030_from_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._write(
                root,
                "GestorWoo/pyproject.toml",
                '[project]\nname = "futonhub"\nversion = "0.3.0"\n',
            )
            self.assertEqual(read_installed_futonhub_version(root), "0.3.0")

    def test_formats_version_with_visual_v(self) -> None:
        self.assertEqual(display_version("0.3.0"), "v0.3.0")
        self.assertEqual(display_version("v0.3.0"), "v0.3.0")

    def test_falls_back_to_futonhub_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._write(root, "GestorWoo/pyproject.toml", "[project]\n")
            self._write(
                root,
                "GestorWoo/src/futonhub/__init__.py",
                '__version__ = "0.2.1"\n',
            )
            self.assertEqual(read_installed_futonhub_version(root), "0.2.1")

    def test_falls_back_to_gestorwoo_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._write(
                root,
                "GestorWoo/src/gestorwoo/__init__.py",
                '__version__: str = "0.2.0"\n',
            )
            self.assertEqual(read_installed_futonhub_version(root), "0.2.0")

    def test_missing_files_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(read_installed_futonhub_version(Path(temp)))

    def test_malformed_toml_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._write(root, "GestorWoo/pyproject.toml", "[project\nversion =")
            errors: list[str] = []
            self.assertIsNone(read_installed_futonhub_version(root, errors.append))
            self.assertTrue(errors)

    def test_empty_version_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            self._write(root, "GestorWoo/pyproject.toml", '[project]\nversion = ""\n')
            self.assertIsNone(read_installed_futonhub_version(root))

    def test_installed_021_remote_030_is_visible_update(self) -> None:
        state = FutonHUBVersionState("a" * 40, "b" * 40, "0.2.1", "0.3.0")
        self.assertEqual(state.installed_display, "v0.2.1")
        self.assertEqual(state.remote_display, "v0.3.0")
        self.assertTrue(state.update_available)
        self.assertEqual(state.status_text, "Hay una nueva versión disponible")

    def test_both_versions_030_and_same_commit_are_current(self) -> None:
        state = FutonHUBVersionState("a" * 40, "a" * 40, "0.3.0", "0.3.0")
        self.assertFalse(state.update_available)
        self.assertEqual(state.status_text, "FutonHUB está actualizado")

    def test_same_version_with_different_commits_still_updates(self) -> None:
        state = FutonHUBVersionState("a" * 40, "b" * 40, "0.3.0", "0.3.0")
        self.assertTrue(state.update_available)
        self.assertTrue(state.same_version_different_commits)

    def test_unknown_versions_with_valid_commits_still_update(self) -> None:
        state = FutonHUBVersionState("a" * 40, "b" * 40, None, None)
        self.assertEqual(state.installed_display, "Desconocida")
        self.assertEqual(state.remote_display, "Desconocida")
        self.assertTrue(state.update_available)

    def test_refresh_after_update_reads_new_installed_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            path = root / "GestorWoo/pyproject.toml"
            path.parent.mkdir(parents=True)
            path.write_text('[project]\nversion = "0.2.1"\n', encoding="utf-8")
            self.assertEqual(read_installed_futonhub_version(root), "0.2.1")
            path.write_text('[project]\nversion = "0.3.0"\n', encoding="utf-8")
            refreshed = read_installed_futonhub_version(root)
            state = FutonHUBVersionState("b" * 40, "b" * 40, refreshed, "0.3.0")
            self.assertEqual(state.installed_display, "v0.3.0")
            self.assertFalse(state.update_available)

    def test_update_comparison_uses_commits_not_versions(self) -> None:
        self.assertTrue(commits_require_update("a" * 40, "b" * 40))
        self.assertFalse(commits_require_update("a" * 40, "a" * 40))

    def test_full_hashes_remain_in_technical_lines(self) -> None:
        installed = "4e18e5cd04aa71141be05adfc5a827b3fe7c43d7"
        remote = "2b2eee8e1dfd976c5fa8d2e150d76938f1639990"
        state = FutonHUBVersionState(installed, remote, "0.2.1", "0.3.0")
        lines = "\n".join(state.technical_lines())
        self.assertIn(installed, lines)
        self.assertIn(remote, lines)
        self.assertIn("Versión instalada: v0.2.1", lines)

    def test_remote_version_exceptions_never_escape(self) -> None:
        errors: list[str] = []
        client = FakeRemoteClient(error=RuntimeError("network exploded"))
        version = fetch_remote_futonhub_version(client, "a" * 40, errors.append)
        self.assertIsNone(version)
        self.assertTrue(errors)

    def test_remote_version_uses_exact_commit_ref_and_pyproject_first(self) -> None:
        commit = "2" * 40
        client = FakeRemoteClient(
            files={
                "GestorWoo/pyproject.toml": '[project]\nversion = "0.3.0"\n'
            }
        )
        self.assertEqual(fetch_remote_futonhub_version(client, commit), "0.3.0")
        self.assertEqual(client.requests[0], ("GestorWoo/pyproject.toml", commit))

    def test_remote_version_falls_back_to_exact_tag(self) -> None:
        client = FakeRemoteClient(tag="v0.2.1")
        self.assertEqual(fetch_remote_futonhub_version(client, "a" * 40), "0.2.1")

    def test_persisted_version_is_auxiliary_and_git_fallback_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("0.0.0+git.abcdef\n", encoding="utf-8")
            self.assertIsNone(read_persisted_futonhub_version(root))
            (root / "SOURCE_INFO.json").write_text(
                json.dumps({"installed_version": "0.3.0"}), encoding="utf-8"
            )
            self.assertEqual(read_persisted_futonhub_version(root), "0.3.0")


    def test_main_ui_uses_semantic_version_titles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "futonhub_auto/gui.py").read_text(encoding="utf-8")
        self.assertIn('"Versión instalada"', source)
        self.assertIn('"Versión disponible"', source)
        self.assertNotIn('(0, "Commit instalado"', source)
        self.assertNotIn('(1, "Commit remoto"', source)

    def test_github_client_decodes_remote_text_file(self) -> None:
        client = GitHubClient("o", "r", "main", "token")
        encoded = base64.b64encode(b'[project]\nversion = "0.3.0"\n').decode()
        client._json = MagicMock(return_value={"encoding": "base64", "content": encoded})
        content = client.fetch_text_file("GestorWoo/pyproject.toml", ref="a" * 40)
        self.assertIn('version = "0.3.0"', content)
        requested = client._json.call_args.args[0]
        self.assertIn("GestorWoo/pyproject.toml", requested)
        self.assertIn("ref=" + "a" * 40, requested)


if __name__ == "__main__":
    unittest.main()
