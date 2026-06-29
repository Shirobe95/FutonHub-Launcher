from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from futonhub_auto.archive import safe_extract_snapshot
from futonhub_auto.errors import ValidationError
from futonhub_auto.github_api import CommitInfo, GitHubClient


class GitHubArchiveTests(unittest.TestCase):
    def test_branch_is_encoded_in_url(self) -> None:
        client = GitHubClient("o", "r", "feature/a b", "t")
        self.assertIn("feature%2Fa%20b", client.commit_url())
        self.assertEqual(client.repo_slug, "o/r")


    def test_snapshot_download_uses_github_json_media_type(self) -> None:
        client = GitHubClient("o", "r", "main", "t")
        commit = CommitInfo(
            sha="a" * 40,
            date="",
            message="",
            archive_url="https://api.github.com/repos/o/r/zipball/" + "a" * 40,
        )
        destination = Path("snapshot.zip")
        with patch.object(client, "_download", return_value=destination) as download:
            result = client.download_snapshot(commit, destination)
        self.assertEqual(result, destination)
        self.assertEqual(
            download.call_args.kwargs["accept"],
            "application/vnd.github+json",
        )

    def test_safe_extract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "a.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("repo/file.txt", "ok")
            extracted = safe_extract_snapshot(archive, root / "out")
            self.assertEqual((extracted / "file.txt").read_text(), "ok")

    def test_zip_slip_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "a.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../evil.txt", "x")
            with self.assertRaises(ValidationError):
                safe_extract_snapshot(archive, root / "out")

    def test_corrupt_zip_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            archive.write_bytes(b"not a zip")
            with self.assertRaises(ValidationError):
                safe_extract_snapshot(archive, root / "out")
