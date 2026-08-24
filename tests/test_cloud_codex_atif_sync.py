from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from integrations.harbor.codex_auth_no_session_baseline import (
    sync_remote_codex_sessions_for_atif,
)
from integrations.harbor.statem_codex import StatemCodex


class _FakeCloudEnvironment:
    def __init__(self, remote_sessions: Path | None):
        self.remote_sessions = remote_sessions
        self.download_calls = 0

    async def is_dir(self, path: str) -> bool:
        return self.remote_sessions is not None

    async def download_dir(self, source_dir: str, target_dir: Path) -> None:
        self.download_calls += 1
        if self.remote_sessions is None:
            raise FileNotFoundError(source_dir)
        shutil.copytree(self.remote_sessions, target_dir, dirs_exist_ok=True)


class _FakeCleanupEnvironment:
    pass


class CloudCodexAtifSyncTest(unittest.TestCase):
    def test_downloads_remote_session_when_cloud_logs_are_not_mounted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote = root / "remote" / "2026" / "08" / "24"
            remote.mkdir(parents=True)
            (remote / "rollout.jsonl").write_text("{}\n", encoding="utf-8")
            logs = root / "local-agent"
            env = _FakeCloudEnvironment(root / "remote")

            downloaded = asyncio.run(
                sync_remote_codex_sessions_for_atif(env, logs)
            )

            self.assertTrue(downloaded)
            self.assertEqual(env.download_calls, 1)
            self.assertTrue(any((logs / "sessions").rglob("*.jsonl")))

    def test_existing_mounted_session_avoids_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs = Path(temp_dir) / "agent"
            session = logs / "sessions" / "one"
            session.mkdir(parents=True)
            (session / "rollout.jsonl").write_text("{}\n", encoding="utf-8")
            env = _FakeCloudEnvironment(None)

            downloaded = asyncio.run(
                sync_remote_codex_sessions_for_atif(env, logs)
            )

            self.assertFalse(downloaded)
            self.assertEqual(env.download_calls, 0)

    def test_missing_remote_session_is_nonfatal_and_leaves_no_raw_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs = Path(temp_dir) / "agent"
            env = _FakeCloudEnvironment(None)

            downloaded = asyncio.run(
                sync_remote_codex_sessions_for_atif(env, logs)
            )

            self.assertFalse(downloaded)
            self.assertFalse((logs / "sessions").exists())

    def test_statem_cleanup_removes_downloaded_local_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs = Path(temp_dir) / "agent"
            session = logs / "sessions" / "one"
            session.mkdir(parents=True)
            (session / "rollout.jsonl").write_text("{}\n", encoding="utf-8")
            agent = StatemCodex.__new__(StatemCodex)
            agent.logs_dir = logs
            agent.exec_as_agent = AsyncMock()

            asyncio.run(
                agent._remove_codex_session_logs(_FakeCleanupEnvironment())
            )

            self.assertFalse((logs / "sessions").exists())
            agent.exec_as_agent.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
