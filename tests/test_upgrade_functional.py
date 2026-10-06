from __future__ import annotations

import hashlib
import io
import json
import socketserver
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from email.message import Message
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from futonhub_auto import archive, flow
from futonhub_auto.config import LauncherConfig
from futonhub_auto.errors import (
    AlreadyRunningError,
    AuthenticationError,
    DownloadError,
    RateLimitError,
    RemoteNotFoundError,
    UpdateError,
    ValidationError,
)
from futonhub_auto.github_api import CommitInfo, GitHubClient, clean_token
from futonhub_auto.github_api import LauncherRelease
from futonhub_auto.locking import FileLock, instance_lock, update_lock
from futonhub_auto.paths import AppPaths
from futonhub_auto.pshell import quote
from futonhub_auto.self_update import build_replacement_script, download_update, parse_checksum
from futonhub_auto.transaction import DirectGitUpdater
from futonhub_auto.versioning import is_newer, parse_release_tag, parse_version


def http_error(code: int, headers: dict[str, str] | None = None, body: bytes = b"") -> HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    error = HTTPError("https://api.github.com/x", code, "x", message, io.BytesIO(body))
    error._body = body  # type: ignore[attr-defined]
    return error


class FakeResponse:
    def __init__(self, payload: bytes = b"{}") -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class ConfigTests(unittest.TestCase):
    def test_corrupt_json_is_backed_up_and_defaults_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "launcher.json"
            path.write_text("{ corrupt", encoding="utf-8")
            config = LauncherConfig.load_or_create(path)
            self.assertEqual(config.branch, "refactor/modularizacion-v1")
            self.assertTrue(config.notices)
            self.assertTrue(list(Path(temp).glob("launcher.json.corrupt-*")))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], 2)

    def test_managed_values_come_from_code_not_from_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "launcher.json"
            path.write_text(
                json.dumps(
                    {
                        "branch": "old-branch",
                        "python_version": "3.13.1",
                        "python_installer_url": "https://old",
                        "python_installer_sha256": "a" * 64,
                        "auto_open_erp": False,
                        "backup_retention": 5,
                    }
                ),
                encoding="utf-8",
            )
            config = LauncherConfig.load_or_create(path)
            self.assertEqual(config.branch, "refactor/modularizacion-v1")
            self.assertEqual(config.python_version, "3.13.14")
            self.assertFalse(config.auto_open_erp)
            self.assertEqual(config.backup_retention, 5)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("branch", saved)
            self.assertNotIn("python_installer_sha256", saved)

    def test_invalid_values_fall_back_with_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "launcher.json"
            path.write_text(json.dumps({"backup_retention": "abc", "auto_open_erp": "yes"}), encoding="utf-8")
            config = LauncherConfig.load_or_create(path)
            self.assertEqual(config.backup_retention, 3)
            self.assertTrue(config.auto_open_erp)
            self.assertEqual(len(config.notices), 2)

    def test_manual_overrides_are_honoured_and_kept(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "launcher.json"
            path.write_text(json.dumps({"schema": 2, "overrides": {"branch": "main"}}), encoding="utf-8")
            config = LauncherConfig.load_or_create(path)
            self.assertEqual(config.branch, "main")
            config.save(path, overrides={"branch": "main"})
            self.assertEqual(json.loads(path.read_text())["overrides"], {"branch": "main"})


class GitHubErrorTests(unittest.TestCase):
    def client(self) -> GitHubClient:
        client = GitHubClient("o", "r", "main", "tok_en123")
        client._sleep = lambda _s: None
        return client

    def fail_with(self, error: HTTPError) -> Exception:
        client = self.client()
        client._opener = MagicMock()

        def again(*args: object, **kwargs: object) -> None:
            raise http_error(error.code, dict(error.headers), getattr(error, "_body", b""))

        client._opener.open.side_effect = again
        with self.assertRaises(Exception) as caught:
            client._json("https://api.github.com/x")
        return caught.exception

    def test_401_is_token_problem(self) -> None:
        self.assertIsInstance(self.fail_with(http_error(401)), AuthenticationError)

    def test_403_without_limit_is_permission_problem(self) -> None:
        error = self.fail_with(http_error(403, body=b'{"message":"Resource not accessible"}'))
        self.assertIsInstance(error, AuthenticationError)
        self.assertNotIsInstance(error, RateLimitError)

    def test_403_with_rate_limit_headers_is_not_a_token_problem(self) -> None:
        error = self.fail_with(http_error(403, {"X-RateLimit-Remaining": "0", "Retry-After": "1"}))
        self.assertIsInstance(error, RateLimitError)

    def test_403_with_rate_limit_message(self) -> None:
        error = self.fail_with(http_error(403, body=b'{"message":"API rate limit exceeded"}'))
        self.assertIsInstance(error, RateLimitError)

    def test_429_is_rate_limit(self) -> None:
        self.assertIsInstance(self.fail_with(http_error(429)), RateLimitError)

    def test_404_is_not_found_not_token(self) -> None:
        error = self.fail_with(http_error(404))
        self.assertIsInstance(error, RemoteNotFoundError)
        self.assertNotIsInstance(error, AuthenticationError)

    def test_503_is_transient_download_error(self) -> None:
        error = self.fail_with(http_error(503))
        self.assertIsInstance(error, DownloadError)

    def test_transient_error_is_retried_then_succeeds(self) -> None:
        client = self.client()
        client._opener = MagicMock()
        client._opener.open.side_effect = [http_error(502), http_error(503), FakeResponse(b'{"ok": true}')]
        self.assertEqual(client._json("https://api.github.com/x"), {"ok": True})
        self.assertEqual(client._opener.open.call_count, 3)

    def test_non_transient_error_is_not_retried(self) -> None:
        client = self.client()
        client._opener = MagicMock()
        client._opener.open.side_effect = http_error(401)
        with self.assertRaises(AuthenticationError):
            client._json("https://api.github.com/x")
        self.assertEqual(client._opener.open.call_count, 1)

    def test_network_errors_are_retried_and_reported(self) -> None:
        client = self.client()
        client._opener = MagicMock()
        client._opener.open.side_effect = TimeoutError("timed out")
        with self.assertRaises(DownloadError):
            client._json("https://api.github.com/x")
        self.assertEqual(client._opener.open.call_count, 3)

    def test_token_is_cleaned_and_validated(self) -> None:
        self.assertEqual(clean_token('  "github_pat_abc"\n'), "github_pat_abc")
        self.assertEqual(clean_token("Bearer ghp_abc"), "ghp_abc")
        with self.assertRaises(AuthenticationError):
            GitHubClient("o", "r", "b", "tok en")
        with self.assertRaises(AuthenticationError):
            GitHubClient("o", "r", "b", "tóken")

    def test_authorization_is_dropped_on_cross_host_redirect(self) -> None:
        seen: dict[int, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                return None

            def do_GET(self) -> None:  # noqa: N802
                seen[self.server.server_address[1]] = self.headers.get("Authorization")
                if self.path.startswith("/start"):
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{second.server_address[1]}/end")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")

        first = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        second = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        for server in (first, second):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = GitHubClient("o", "r", "b", "secret_tok")
            with client._open(
                f"http://127.0.0.1:{first.server_address[1]}/start", accept="x", timeout=5
            ) as response:
                response.read()
        finally:
            first.shutdown()
            second.shutdown()
            first.server_close()
            second.server_close()
        self.assertEqual(seen[first.server_address[1]], "Bearer secret_tok")
        self.assertIsNone(seen[second.server_address[1]])


class ReleaseSelectionTests(unittest.TestCase):
    @staticmethod
    def release(tag: str, **extra: object) -> dict:
        base = {
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "published_at": "x",
            "assets": [
                {"name": "FutonHUB-Launcher.exe", "url": f"{tag}/exe"},
                {"name": "FutonHUB-Launcher.exe.sha256", "url": f"{tag}/sha"},
            ],
        }
        base.update(extra)
        return base

    def pick(self, listing: list[dict]) -> str | None:
        client = GitHubClient("o", "r", "main", require_auth=False)
        client._json = MagicMock(return_value=listing)  # type: ignore[method-assign]
        found = client.latest_launcher_release()
        return found.tag_name if found else None

    def test_highest_version_wins_regardless_of_order(self) -> None:
        self.assertEqual(
            self.pick([self.release("launcher-v0.11.0"), self.release("launcher-v0.13.0"), self.release("launcher-v0.9.9")]),
            "launcher-v0.13.0",
        )

    def test_suffixed_and_unicode_tags_are_ignored(self) -> None:
        self.assertEqual(
            self.pick([self.release("launcher-v0.14.0-rc1"), self.release("launcher-v\uff10.\uff11\uff15.0"), self.release("launcher-v0.12.0")]),
            "launcher-v0.12.0",
        )

    def test_release_without_checksum_asset_is_skipped(self) -> None:
        broken = self.release("launcher-v0.14.0")
        broken["assets"] = broken["assets"][:1]
        self.assertEqual(self.pick([broken, self.release("launcher-v0.12.0")]), "launcher-v0.12.0")

    def test_version_parsing_is_ascii_only(self) -> None:
        self.assertIsNone(parse_release_tag("launcher-v\uff11.\uff12.\uff13"))
        with self.assertRaises(ValueError):
            parse_version("\uff11.\uff12.\uff13")
        self.assertTrue(is_newer("0.13.0", "0.12.0"))


class SelfUpdateTests(unittest.TestCase):
    GOOD = hashlib.sha256(b"exe").hexdigest()

    def test_checksum_formats(self) -> None:
        self.assertEqual(parse_checksum(f"{self.GOOD}  FutonHUB-Launcher.exe\r\n"), self.GOOD)
        self.assertEqual(parse_checksum(f"{self.GOOD.upper()}\n"), self.GOOD)
        self.assertEqual(parse_checksum(f"{self.GOOD} *FutonHUB-Launcher.exe"), self.GOOD)

    def test_checksum_rejections(self) -> None:
        for text in ("", "   \n", f"{self.GOOD}  other.exe", f"{self.GOOD}\n{self.GOOD}", f"text {self.GOOD} text", self.GOOD + "0", "zz" * 32):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_checksum(text)

    def test_mismatch_removes_downloaded_executable(self) -> None:
        class Client:
            def download_launcher_asset(self, url, destination, progress=None):
                if url == "exe":
                    destination.write_bytes(b"tampered")
                else:
                    destination.write_text(f"{SelfUpdateTests.GOOD}  FutonHUB-Launcher.exe")
                return destination

        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            release = LauncherRelease("9.9.9", "launcher-v9.9.9", "exe", "sha", "")
            with self.assertRaises(ValidationError):
                download_update(Client(), release, paths, lambda _t: None)
            self.assertFalse((paths.downloads / "Launcher" / "9.9.9" / "FutonHUB-Launcher.exe").exists())

    def test_powershell_quote_escapes_every_quote_kind(self) -> None:
        self.assertEqual(quote("a'b"), "'a''b'")
        self.assertEqual(quote("O\u2019Brien"), "'O\u2019\u2019Brien'")
        self.assertEqual(quote("x\u2018y"), "'x\u2018\u2018y'")
        with self.assertRaises(ValueError):
            quote("a\nb")

    def test_replacement_script_escapes_curly_quotes(self) -> None:
        script = build_replacement_script(Path("C:/Users/O\u2019B/x.exe"), Path("C:/t/y.exe"), pid=5)
        self.assertIn("O\u2019\u2019B", script)


class ArchiveHardeningTests(unittest.TestCase):
    def extract(self, entries: dict[str, bytes]) -> Path:
        temp = Path(tempfile.mkdtemp())
        zip_path = temp / "a.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as handle:
            for name, data in entries.items():
                handle.writestr(name, data)
        return archive.safe_extract_snapshot(zip_path, temp / "out")

    def test_windows_hostile_names_are_rejected(self) -> None:
        for name in ("r/CON", "r/aux.txt", "r/file.txt:stream", "r/trailing.", "r\\..\\evil", "r/a<b", "r/dir /x"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.extract({name: b"x"})

    def test_normal_names_are_accepted(self) -> None:
        root = self.extract({"r/Abrir ERP.bat": b"x", "r/GestorWoo/src/a_b-c.py": b"y"})
        self.assertTrue((root / "Abrir ERP.bat").is_file())

    def test_too_many_entries_rejected(self) -> None:
        with patch.object(archive, "MAX_ENTRIES", 2), self.assertRaises(ValidationError):
            self.extract({"r/a": b"1", "r/b": b"2", "r/c": b"3"})

    def test_decompression_bomb_rejected(self) -> None:
        with patch.object(archive, "MAX_TOTAL_BYTES", 1024 * 1024), self.assertRaises(ValidationError):
            self.extract({"r/big.bin": b"\0" * (2 * 1024 * 1024)})

    def test_high_ratio_big_file_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.extract({"r/big.bin": b"\0" * (64 * 1024 * 1024)})


class LockingTests(unittest.TestCase):
    def test_second_instance_is_rejected_until_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first, second = instance_lock(Path(temp)), instance_lock(Path(temp))
            first.acquire()
            with self.assertRaises(AlreadyRunningError):
                second.acquire()
            first.release()
            second.acquire()
            second.release()

    def test_only_one_concurrent_updater_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            outcomes: list[str] = []
            barrier = threading.Barrier(2)

            def worker() -> None:
                lock = update_lock(Path(temp))
                barrier.wait()
                try:
                    lock.acquire()
                except AlreadyRunningError:
                    outcomes.append("busy")
                    return
                time.sleep(0.3)
                outcomes.append("ran")
                lock.release()

            threads = [threading.Thread(target=worker) for _ in range(2)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(sorted(outcomes), ["busy", "ran"])

    def test_lock_object_cannot_be_acquired_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            lock = FileLock(Path(temp) / "x.lock", "busy")
            lock.acquire()
            with self.assertRaises(AlreadyRunningError):
                lock.acquire()
            lock.release()


def make_app(paths: AppPaths, commit: str, marker: str = "") -> None:
    app = paths.app
    (app / "GestorWoo").mkdir(parents=True, exist_ok=True)
    (app / "Abrir ERP.bat").write_text("x")
    (app / "GestorWoo/gestorwoo.py").write_text("x")
    (app / "SOURCE_COMMIT").write_text(commit + "\n")
    (app / "runtime_python.txt").write_text(sys.executable + "\n")
    (app / "marker.txt").write_text(marker)


class FlowTests(unittest.TestCase):
    def collect(self, paths: AppPaths, client_factory, frozen: bool = False, config: LauncherConfig | None = None):
        events: list[tuple[str, object]] = []
        started = flow.StartupFlow(
            paths, config or LauncherConfig(), lambda event, payload: events.append((event, payload)),
            frozen=frozen, client_factory=client_factory,
        )
        started.run("tok_en123")
        return events

    def failing_client(self, error: Exception):
        class Client:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def resolve_head(self):
                raise error

        return Client

    def test_decision_matrix(self) -> None:
        cases = [
            (AuthenticationError("t"), "token", True),
            (RemoteNotFoundError("n"), "not_found", False),
            (RateLimitError("r"), "rate_limit", False),
            (DownloadError("d"), "network", False),
            (ValidationError("v"), "update_failed", False),
            (UpdateError("u"), "update_failed", False),
        ]
        for error, kind, ask in cases:
            with self.subTest(kind=kind):
                ready = flow.decide_failure(error, True)
                self.assertEqual((ready.kind, ready.open_local, ready.ask_token), (kind, True, ask))
                cold = flow.decide_failure(error, False)
                self.assertFalse(cold.open_local)
        self.assertFalse(flow.decide_failure(RuntimeError("x"), True).open_local)
        self.assertEqual(flow.decide_failure(AlreadyRunningError("b"), True).kind, "busy")

    def test_expired_token_with_local_install_opens_local_and_asks_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            make_app(paths, "a" * 40)
            events = self.collect(paths, self.failing_client(AuthenticationError("token caducado")))
            names = [name for name, _ in events]
            self.assertIn("degraded", names)
            self.assertNotIn("failed", names)
            decision = dict(events)["degraded"]
            self.assertTrue(decision.ask_token)

    def test_failure_without_local_install_is_reported_not_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            events = self.collect(paths, self.failing_client(RemoteNotFoundError("rama")))
            self.assertIn("failed", [name for name, _ in events])

    def test_rate_limit_does_not_ask_for_new_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            make_app(paths, "a" * 40)
            decision = dict(self.collect(paths, self.failing_client(RateLimitError("limite"))))["degraded"]
            self.assertFalse(decision.ask_token)

    def test_launcher_self_update_runs_even_if_erp_token_is_bad(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            calls: list[str] = []

            def factory(owner, repo, branch, token="", **kwargs):
                calls.append(repo)
                return self.failing_client(AuthenticationError("bad"))(owner, repo, branch, token)

            release = LauncherRelease("9.0.0", "launcher-v9.0.0", "e", "s", "")
            with patch.object(flow, "find_update", return_value=release), patch.object(
                flow, "download_update", return_value=MagicMock()
            ), patch.object(flow, "schedule_update") as schedule:
                events = self.collect(paths, factory, frozen=True)
            schedule.assert_called_once()
            self.assertIn("launcher_restarting", [name for name, _ in events])
            self.assertNotIn("FutonEspaiHUB", calls)

    def test_self_update_failure_does_not_block_erp_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            make_app(paths, "a" * 40)
            with patch.object(flow, "find_update", side_effect=DownloadError("sin red")):
                events = self.collect(paths, self.failing_client(DownloadError("sin red")), frozen=True)
            self.assertIn("degraded", [name for name, _ in events])

    def test_pinned_version_skips_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            sha = "a" * 40
            make_app(paths, sha)
            DirectGitUpdater(paths, LauncherConfig(), lambda _t: None, lambda _w, _t: None).set_pin(sha, "test")

            class Client:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    pass

                def resolve_head(self):
                    return CommitInfo("b" * 40, "", "", "u")

            with patch.object(DirectGitUpdater, "install_commit", side_effect=AssertionError("no debe actualizar")):
                events = self.collect(paths, Client)
            self.assertIn("success", [name for name, _ in events])


class RestoreTests(unittest.TestCase):
    def updater(self, paths: AppPaths) -> DirectGitUpdater:
        return DirectGitUpdater(paths, LauncherConfig(), lambda _t: None, lambda _w, _t: None)

    def test_restore_keeps_local_data_and_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            old, new = "a" * 40, "b" * 40
            make_app(paths, old, "old")
            backup = paths.rollback / old[:12]
            import shutil

            shutil.copytree(paths.app, backup)
            shutil.rmtree(paths.app)
            make_app(paths, new, "new")
            (paths.app / "GestorWoo").mkdir(exist_ok=True)
            (paths.app / "GestorWoo/.env").write_text("SECRET=1")
            updater = self.updater(paths)
            self.assertEqual([row[1] for row in updater.list_backups()], [old])
            with patch.object(DirectGitUpdater, "_health"):
                outcome = updater.restore_backup(old[:12])
            self.assertEqual(updater.local_commit(), old)
            self.assertEqual((paths.app / "marker.txt").read_text(), "old")
            self.assertEqual((paths.app / "GestorWoo/.env").read_text(), "SECRET=1")
            self.assertEqual(updater.pinned_commit(), old)
            self.assertIn("pausa", outcome.message)
            self.assertTrue(any(row[1] == new for row in updater.list_backups()))
            self.assertFalse(paths.app.with_name("App.__previous__").exists())

    def test_failed_restore_keeps_current_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            old, new = "a" * 40, "b" * 40
            make_app(paths, old)
            import shutil

            shutil.copytree(paths.app, paths.rollback / "old")
            shutil.rmtree(paths.app)
            make_app(paths, new, "new")
            with patch.object(DirectGitUpdater, "_health", side_effect=ValidationError("boom")):
                with self.assertRaises(ValidationError):
                    self.updater(paths).restore_backup("old")
            self.assertEqual(self.updater(paths).local_commit(), new)
            self.assertEqual(self.updater(paths).pinned_commit(), "")

    def test_restore_rejects_path_traversal_and_missing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            with self.assertRaises(ValidationError):
                self.updater(paths).restore_backup("../x")
            make_app(paths, "a" * 40)
            import shutil

            shutil.copytree(paths.app, paths.rollback / "old")
            (paths.rollback / "old/runtime_python.txt").write_text(str(Path(temp) / "gone.exe"))
            with self.assertRaises(ValidationError):
                self.updater(paths).restore_backup("old")

    def test_recover_does_nothing_while_another_instance_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            make_app(paths, "a" * 40)
            paths.state.joinpath("transaction.json").write_text(json.dumps({"phase": "swapped"}))
            paths.app.with_name("App.__previous__").mkdir()
            with update_lock(paths.state):
                self.assertIsNone(self.updater(paths).recover())
            self.assertTrue(paths.app.with_name("App.__previous__").exists())

    def test_health_timeout_becomes_validation_error(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            paths = AppPaths.from_root(Path(temp) / "F")
            paths.ensure()
            with patch("futonhub_auto.transaction.subprocess.run", side_effect=subprocess.TimeoutExpired("x", 1)):
                with self.assertRaises(ValidationError):
                    self.updater(paths)._health(paths.app, Path(sys.executable))


class RuntimeTagTests(unittest.TestCase):
    def test_venv_directory_includes_python_tag(self) -> None:
        from futonhub_auto import python_runtime

        tag = python_runtime.python_tag(Path(sys.executable))
        self.assertRegex(tag, r"^py\d{2,3}$")
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "app"
            app.mkdir()
            (app / "requirements_erp.txt").write_text("requests\n")
            with patch.object(python_runtime, "_run") as run:
                try:
                    python_runtime.prepare_runtime(app, Path(temp) / "rt", Path(sys.executable), lambda _t: None)
                except Exception:
                    pass
            first_call = run.call_args_list[0].args[0]
            self.assertIn(tag, first_call[-1])


class ProtectedPathsTests(unittest.TestCase):
    def test_runtime_data_directories_are_protected(self) -> None:
        from futonhub_auto.deployment import PROTECTED_PATHS

        for relative in ("GestorWoo/.env", "GestorWoo/data", "GestorWoo/exports", "GestorWoo/logs", "GestorWoo/backups"):
            self.assertIn(relative, PROTECTED_PATHS)


if __name__ == "__main__":
    unittest.main()
