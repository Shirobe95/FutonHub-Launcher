from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from futonhub_auto.deployment import create_runtime, preserve_existing


def make_snapshot(root: Path) -> None:
    for relative in (
        "GestorWoo/gestorwoo.py",
        "GestorWoo/src/futonhub/app/cli.py",
        "GestorWoo/src/futonhub/ui/erp/prototype.py",
        "CalculoCoste/coste_pedido.py",
        "CalculoCoste/coste.py",
        "CalculoCoste/coste_1.py",
        "CalculoCoste/constantes_negocio.json",
        "CalculoCoste/data.xlsx",
        "requirements_erp.txt",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "x", encoding="utf-8")


class DeploymentTests(unittest.TestCase):
    def test_runtime_excludes_env_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            make_snapshot(source)
            (source / "GestorWoo/.env").write_text("SECRET")
            test_file = source / "GestorWoo/tests/x.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("x")
            destination = root / "app"
            create_runtime(
                source,
                destination,
                commit="a" * 40,
                repository="o/r",
                branch="b",
                commit_date="d",
                archive_sha256="h",
            )
            self.assertFalse((destination / "GestorWoo/.env").exists())
            self.assertFalse((destination / "GestorWoo/tests").exists())
            self.assertTrue((destination / "SOURCE_COMMIT").exists())

    def test_entrypoint_uses_runtime_file_and_launcher_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            make_snapshot(source)
            destination = root / "app"
            create_runtime(
                source,
                destination,
                commit="b" * 40,
                repository="o/r",
                branch="b",
                commit_date="d",
                archive_sha256="h",
            )
            text = (destination / "Abrir ERP.bat").read_text()
            self.assertIn("runtime_python.txt", text)
            self.assertIn("FUTONHUB_LAUNCHER", text)

    def test_preserves_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "current"
            staged = root / "staged"
            (current / "GestorWoo").mkdir(parents=True)
            (current / "GestorWoo/.env").write_text("A=1")
            staged.mkdir()
            values = preserve_existing(current, staged)
            self.assertIn("GestorWoo/.env", values)
            self.assertEqual((staged / "GestorWoo/.env").read_text(), "A=1")

    def test_source_info_records_exact_commit(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            make_snapshot(source)
            destination = root / "app"
            commit = "c" * 40
            create_runtime(source, destination, commit=commit, repository="o/r", branch="b", commit_date="2026", archive_sha256="hash")
            info = json.loads((destination / "SOURCE_INFO.json").read_text())
            self.assertEqual(info["commit"], commit)
            self.assertEqual((destination / "SOURCE_COMMIT").read_text().strip(), commit)

    def test_local_constants_are_not_protected_because_supabase_is_the_source_of_truth(self) -> None:
        from futonhub_auto.deployment import PROTECTED_PATHS

        self.assertNotIn("CalculoCoste/constantes_negocio.json", PROTECTED_PATHS)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current, staged = root / "current", root / "staged"
            old = current / "CalculoCoste/constantes_negocio.json"
            old.parent.mkdir(parents=True)
            old.write_text('{"stale": true}')
            staged.mkdir()
            preserve_existing(current, staged)
            self.assertFalse((staged / "CalculoCoste/constantes_negocio.json").exists())

class ManagedSupportFilesTests(unittest.TestCase):
    def test_refresh_repairs_entrypoint_without_touching_erp_source(self) -> None:
        from futonhub_auto.deployment import refresh_managed_files
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "App"
            source = app / "GestorWoo/gestorwoo.py"
            source.parent.mkdir(parents=True)
            source.write_text("original", encoding="utf-8")
            (app / "Abrir ERP.bat").write_text("broken", encoding="ascii")
            changed = refresh_managed_files(app)
            self.assertTrue(changed)
            self.assertEqual(source.read_text(encoding="utf-8"), "original")
            entrypoint = (app / "Abrir ERP.bat").read_text(encoding="ascii")
            self.assertIn("pushd", entrypoint)
            self.assertIn("PYTHONUTF8", entrypoint)
            self.assertTrue((app / "health_check.py").is_file())


class ConstantsNotRequiredTests(unittest.TestCase):
    def test_health_check_does_not_look_at_local_constants(self) -> None:
        from futonhub_auto.deployment import HEALTH_CHECK

        self.assertNotIn("constantes_negocio", HEALTH_CHECK)
        self.assertNotIn("constants_json", HEALTH_CHECK)
