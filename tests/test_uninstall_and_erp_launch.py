from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import unittest

from futonhub_auto.credentials import MemoryCredentialStore
from futonhub_auto.desktop import (
    build_clean_erp_environment,
    clean_external_process_dll_search,
    launch_erp,
)
from futonhub_auto.paths import AppPaths
from futonhub_auto.uninstall import build_cleanup_script, schedule_full_uninstall


class ErpLaunchTests(unittest.TestCase):
    def test_launch_uses_managed_python_directly_and_captures_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "App"
            logs = root / "Logs"
            runtime = root / "Runtime/python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"x")
            gestorwoo = app / "GestorWoo"
            gestorwoo.mkdir(parents=True)
            script = gestorwoo / "gestorwoo.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            (app / "Abrir ERP.bat").write_text("@echo off\n", encoding="ascii")
            (app / "runtime_python.txt").write_text(str(runtime), encoding="utf-8")
            process = MagicMock()
            with patch("futonhub_auto.desktop.IS_WINDOWS", True), patch(
                "futonhub_auto.desktop.subprocess.Popen", return_value=process
            ) as popen:
                result = launch_erp(app, logs)
            self.assertIs(result.process, process)
            self.assertTrue(result.log_path.is_file())
            args = popen.call_args.args[0]
            self.assertEqual(args, [str(runtime), str(script), "erp-prototype"])
            self.assertNotIn("cmd.exe", " ".join(args).lower())
            self.assertEqual(popen.call_args.kwargs["cwd"], str(gestorwoo))

    def test_clean_environment_removes_pyinstaller_tcl_and_python_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            meipass = root / "_MEI12345"
            runtime = root / "Runtime/venv/Scripts/python.exe"
            polluted_path = os.pathsep.join(
                [str(meipass), str(meipass / "bin"), str(root / "Windows/System32")]
            )
            with patch.dict(
                "os.environ",
                {
                    "PATH": polluted_path,
                    "TCL_LIBRARY": str(meipass / "tcl_data"),
                    "TK_LIBRARY": str(meipass / "tk_data"),
                    "PYTHONHOME": str(meipass),
                    "PYTHONPATH": str(meipass / "base_library.zip"),
                    "_PYI_APPLICATION_HOME_DIR": str(meipass),
                },
                clear=True,
            ), patch.object(
                __import__("futonhub_auto.desktop", fromlist=["sys"]).sys,
                "_MEIPASS",
                str(meipass),
                create=True,
            ):
                environment, removed = build_clean_erp_environment(runtime)

            self.assertNotIn("TCL_LIBRARY", environment)
            self.assertNotIn("TK_LIBRARY", environment)
            self.assertNotIn("PYTHONHOME", environment)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertNotIn("_PYI_APPLICATION_HOME_DIR", environment)
            self.assertEqual(environment["PATH"].split(os.pathsep)[0], str(runtime.parent))
            self.assertNotIn(str(meipass), environment["PATH"])
            self.assertIn("TCL_LIBRARY", removed)
            self.assertEqual(environment["PYTHONNOUSERSITE"], "1")

    def test_frozen_launcher_restores_default_dll_search_for_child(self) -> None:
        import futonhub_auto.desktop as desktop

        frozen_root = r"C:\Users\Test\AppData\Local\Temp\_MEI12345"
        with patch.object(desktop, "IS_WINDOWS", True), patch.object(
            desktop.sys, "frozen", True, create=True
        ), patch.object(
            desktop.sys, "_MEIPASS", frozen_root, create=True
        ), patch.object(desktop, "_set_windows_dll_directory") as setter:
            with clean_external_process_dll_search():
                pass

        self.assertEqual(setter.call_args_list, [call(None), call(frozen_root)])

    def test_launch_requires_official_manual_entrypoint_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "App"
            logs = root / "Logs"
            runtime = root / "Runtime/python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"x")
            gestorwoo = app / "GestorWoo"
            gestorwoo.mkdir(parents=True)
            (gestorwoo / "gestorwoo.py").write_text("", encoding="utf-8")
            (app / "runtime_python.txt").write_text(str(runtime), encoding="utf-8")
            with patch("futonhub_auto.desktop.IS_WINDOWS", True):
                with self.assertRaisesRegex(Exception, "Abrir ERP.bat"):
                    launch_erp(app, logs)


class UninstallTests(unittest.TestCase):
    def test_cleanup_script_deletes_root_and_shortcut_literally(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            script = build_cleanup_script(paths, pid=123)
            self.assertIn("Wait-Process -Id $LauncherPid", script)
            self.assertIn(str(paths.root), script)
            self.assertIn("Remove-Item -LiteralPath $InstallRoot -Recurse -Force", script)
            self.assertNotIn("Remove-Item *", script)

    def test_schedule_removes_credential_and_uses_temp_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "FutonHUB")
            store = MemoryCredentialStore()
            store.write("cred", "secret")
            process = MagicMock()
            with patch("futonhub_auto.uninstall.IS_WINDOWS", True), patch(
                "futonhub_auto.uninstall.tempfile.gettempdir", return_value=temp
            ), patch(
                "futonhub_auto.uninstall.subprocess.Popen", return_value=process
            ) as popen:
                script = schedule_full_uninstall(paths, store, "cred", pid=456)
            self.assertIsNone(store.read("cred"))
            self.assertTrue(script.is_file())
            self.assertNotEqual(script.parent, paths.root)
            command = popen.call_args.args[0]
            self.assertIn("powershell.exe", command[0])
            self.assertIn(str(script), command)
