"""Tests for ArtifactWatcher — version creation, dedupe, sanitization, deletion."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from cowork.artifact_watcher import ArtifactWatcher
from cowork.event_bus import Topic
from cowork.models import PermissionDecision
from cowork.storage import Storage


@pytest.fixture()
def session_id():
    return uuid4()


@pytest.fixture()
async def storage():
    s = Storage(":memory:")
    await s.init()
    yield s
    await s.close()


@pytest.fixture()
def outputs(tmp_path: Path) -> Path:
    d = tmp_path / "outputs"
    d.mkdir()
    return d


@pytest.fixture()
def arts_dir(tmp_path: Path, session_id, monkeypatch):
    d = tmp_path / "sessions" / str(session_id) / "artifacts"
    d.mkdir(parents=True)
    monkeypatch.setattr("cowork.artifact_watcher.config.artifacts_dir", lambda sid: d)
    monkeypatch.setattr("cowork.artifact_watcher.config.outputs_dir", lambda sid: tmp_path / "outputs")
    return d


@pytest.fixture()
async def insert_session(storage, session_id, outputs):
    from cowork.models import Session

    session = Session(id=session_id, prompt="test", outputs_dir=outputs)
    await storage.insert_session(session)
    return session


@pytest.fixture()
def events() -> list[tuple[Topic, dict[str, Any]]]:
    return []


@pytest.fixture()
def watcher(storage, events) -> ArtifactWatcher:
    def publish(topic: Topic, payload: dict[str, Any]) -> None:
        events.append((topic, payload))

    return ArtifactWatcher(storage=storage, publish=publish)


class TestVersionFile:
    @pytest.mark.asyncio()
    async def test_new_file_creates_version(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session, events
    ):
        f = outputs / "report.txt"
        f.write_text("hello world")

        result = await watcher.version_file(session_id, "report.txt", f)

        assert result is not None
        assert result.version == 1
        assert result.content_hash != ""

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].name == "report.txt"
        assert artifacts[0].current_version == 1

        assert len(events) == 1
        assert events[0][0] == Topic.ARTIFACT
        assert events[0][1]["type"] == "artifact.created"

    @pytest.mark.asyncio()
    async def test_update_with_different_content(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session, events
    ):
        f = outputs / "data.csv"
        f.write_text("a,b,c")
        await watcher.version_file(session_id, "data.csv", f)

        f.write_text("a,b,c,d")
        result = await watcher.version_file(session_id, "data.csv", f)

        assert result is not None
        assert result.version == 2

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].current_version == 2

        assert len(events) == 2
        assert events[0][1]["type"] == "artifact.created"
        assert events[1][1]["type"] == "artifact.updated"

    @pytest.mark.asyncio()
    async def test_dedupe_identical_hash(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session
    ):
        f = outputs / "same.txt"
        f.write_text("identical content")
        first = await watcher.version_file(session_id, "same.txt", f)
        assert first is not None

        second = await watcher.version_file(session_id, "same.txt", f)
        assert second is None

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].current_version == 1


class TestNameSanitization:
    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "bad_name",
        [
            "",
            ".",
            "..",
            "../../../etc/passwd",
            "foo/bar",
            "a/../b",
        ],
    )
    async def test_rejects_bad_names(
        self, watcher, session_id, outputs, arts_dir, insert_session, bad_name
    ):
        f = outputs / "legit.txt"
        f.write_text("content")
        result = await watcher.version_file(session_id, bad_name, f)
        assert result is None


class TestVersionedPathFormat:
    @pytest.mark.asyncio()
    async def test_path_format(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session
    ):
        f = outputs / "chart.png"
        f.write_bytes(b"\x89PNG fake data")
        result = await watcher.version_file(session_id, "chart.png", f)
        assert result is not None

        versioned_files = list(arts_dir.iterdir())
        assert len(versioned_files) == 1
        vf = versioned_files[0]
        assert vf.name.startswith("chart__v1_")
        assert vf.name.endswith(".png")
        assert len(vf.name.split("_")[-1].split(".")[0]) == 8


class TestDeletion:
    @pytest.mark.asyncio()
    async def test_deletion_marks_artifact(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session, events
    ):
        f = outputs / "temp.txt"
        f.write_text("temporary")
        await watcher.version_file(session_id, "temp.txt", f)
        events.clear()

        await watcher._handle_deletion(session_id, "temp.txt")

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].deleted_at is not None

        perms = await storage.list_permissions(session_id)
        assert len(perms) == 1
        assert perms[0].decision == PermissionDecision.DELETED_OBSERVED
        assert perms[0].tool_name == "fs_delete"

        assert len(events) == 1
        assert events[0][1]["type"] == "artifact.deleted"


class TestDotfileExclusion:
    @pytest.mark.asyncio()
    async def test_dotfiles_skipped_in_scan(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session
    ):
        (outputs / ".hidden").write_text("secret")
        (outputs / "visible.txt").write_text("public")

        await watcher._scan_dir(session_id, outputs)

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].name == "visible.txt"


class TestInitialScan:
    @pytest.mark.asyncio()
    async def test_existing_files_versioned_on_watch(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session, monkeypatch
    ):
        (outputs / "pre_existing.txt").write_text("already here")
        (outputs / ".dotfile").write_text("hidden")
        sub = outputs / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content")

        monkeypatch.setattr(
            "cowork.artifact_watcher.ArtifactWatcher._watch_loop",
            lambda *a, **kw: asyncio.sleep(0),
        )

        await watcher.watch(session_id, outputs)
        await asyncio.sleep(0.01)

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].name == "pre_existing.txt"


class TestWatcherLifecycle:
    @pytest.mark.asyncio()
    async def test_stop_watching_does_final_scan(
        self, watcher, storage, session_id, outputs, arts_dir, insert_session, monkeypatch
    ):
        monkeypatch.setattr(
            "cowork.artifact_watcher.ArtifactWatcher._watch_loop",
            lambda *a, **kw: asyncio.sleep(999),
        )
        await watcher.watch(session_id, outputs)

        (outputs / "late_write.txt").write_text("written after watch started")
        await watcher.stop_watching(session_id)

        artifacts = await storage.list_artifacts(session_id)
        assert len(artifacts) == 1
        assert artifacts[0].name == "late_write.txt"

    @pytest.mark.asyncio()
    async def test_no_publish_without_callback(
        self, storage, session_id, outputs, arts_dir, insert_session
    ):
        w = ArtifactWatcher(storage=storage, publish=None)
        f = outputs / "file.txt"
        f.write_text("content")
        result = await w.version_file(session_id, "file.txt", f)
        assert result is not None
