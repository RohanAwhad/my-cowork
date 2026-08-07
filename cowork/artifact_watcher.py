"""ArtifactWatcher — file detection, hash-based versioning, preview surfacing (05 §1.6)."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from watchfiles import Change, awatch

from cowork import config
from cowork.event_bus import Topic
from cowork.models import ArtifactVersion, PermissionDecision
from cowork.storage import Storage

_DEBOUNCE_MS = 100


def _is_dotfile(name: str) -> bool:
    return name.startswith(".")


def _sanitize_name(name: str) -> bool:
    if not name:
        return False
    if name in (".", ".."):
        return False
    if ".." in name.split("/"):
        return False
    if "/" in name:
        return False
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _versioned_name(name: str, version: int, content_hash: str) -> str:
    stem = Path(name).stem
    suffix = Path(name).suffix
    hash8 = content_hash[:8]
    return f"{stem}__v{version}_{hash8}{suffix}"


class ArtifactWatcher:
    """Watches session output directories for file changes, versions artifacts."""

    def __init__(
        self,
        storage: Storage,
        publish: Callable[[Topic, dict[str, Any]], None] | None = None,
    ) -> None:
        self._storage = storage
        self._publish = publish
        self._watchers: dict[UUID, asyncio.Task[None]] = {}
        self._stop_events: dict[UUID, asyncio.Event] = {}
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}
        self._hashes: dict[str, str] = {}

    async def watch(self, session_id: UUID, outputs_dir: Path) -> None:
        logger.debug("artifact_watcher.watch session_id={} dir={}", session_id, outputs_dir)
        arts_dir = config.artifacts_dir(str(session_id))
        arts_dir.mkdir(parents=True, exist_ok=True)

        await self._initial_scan(session_id, outputs_dir)

        stop_event = asyncio.Event()
        self._stop_events[session_id] = stop_event
        task = asyncio.create_task(
            self._watch_loop(session_id, outputs_dir, stop_event)
        )
        self._watchers[session_id] = task

    async def stop_watching(self, session_id: UUID) -> None:
        logger.debug("artifact_watcher.stop_watching session_id={}", session_id)
        stop_event = self._stop_events.pop(session_id, None)
        if stop_event is not None:
            stop_event.set()

        task = self._watchers.pop(session_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        outputs_dir = config.outputs_dir(str(session_id))
        if outputs_dir.is_dir():
            await self._scan_dir(session_id, outputs_dir)

    async def version_file(
        self, session_id: UUID, name: str, fs_path: Path
    ) -> ArtifactVersion | None:
        if not _sanitize_name(name):
            logger.error("artifact_watcher.version_file rejected name={!r}", name)
            return None

        if not fs_path.is_file():
            logger.debug("artifact_watcher.version_file path not a file: {}", fs_path)
            return None

        content_hash = _sha256(fs_path)
        size_bytes = fs_path.stat().st_size

        cache_key = f"{session_id}:{name}"
        if self._hashes.get(cache_key) == content_hash:
            logger.debug("artifact_watcher.version_file dedupe name={}", name)
            return None
        self._hashes[cache_key] = content_hash

        arts_dir = config.artifacts_dir(str(session_id))
        arts_dir.mkdir(parents=True, exist_ok=True)

        artifacts = await self._storage.list_artifacts(session_id)
        existing = next((a for a in artifacts if a.name == name), None)
        next_version = (existing.current_version + 1) if existing else 1

        versioned_name = _versioned_name(name, next_version, content_hash)
        versioned_path = arts_dir / versioned_name
        shutil.copy2(fs_path, versioned_path)

        rel_path = name
        stored_rel_path = str(versioned_path.relative_to(arts_dir.parent.parent))

        _artifact, art_version = await self._storage.record_artifact(
            session_id=session_id,
            name=name,
            rel_path=rel_path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            stored_rel_path=stored_rel_path,
        )

        event_type = "artifact.updated" if existing else "artifact.created"
        if self._publish is not None:
            self._publish(
                Topic.ARTIFACT,
                {
                    "type": event_type,
                    "session_id": str(session_id),
                    "artifact_id": str(_artifact.id),
                    "name": name,
                    "version": art_version.version,
                },
            )

        logger.debug(
            "artifact_watcher.version_file {} name={} v={}",
            event_type, name, art_version.version,
        )
        return art_version

    async def _initial_scan(self, session_id: UUID, outputs_dir: Path) -> None:
        if not outputs_dir.is_dir():
            return
        await self._scan_dir(session_id, outputs_dir)

    async def _scan_dir(self, session_id: UUID, outputs_dir: Path) -> None:
        for entry in outputs_dir.iterdir():
            if not entry.is_file():
                continue
            if _is_dotfile(entry.name):
                continue
            await self.version_file(session_id, entry.name, entry)

    async def _watch_loop(
        self, session_id: UUID, outputs_dir: Path, stop_event: asyncio.Event
    ) -> None:
        logger.debug("artifact_watcher._watch_loop started session_id={}", session_id)
        try:
            async for changes in awatch(outputs_dir, stop_event=stop_event, recursive=False):
                for change_type, path_str in changes:
                    path = Path(path_str)
                    if _is_dotfile(path.name):
                        continue

                    if change_type in (Change.added, Change.modified):
                        debounce_key = f"{session_id}:{path.name}"
                        existing_task = self._debounce_tasks.pop(debounce_key, None)
                        if existing_task is not None and not existing_task.done():
                            existing_task.cancel()
                        self._debounce_tasks[debounce_key] = asyncio.create_task(
                            self._debounced_version(session_id, path.name, path, debounce_key)
                        )
                    elif change_type == Change.deleted:
                        await self._handle_deletion(session_id, path.name)
        except asyncio.CancelledError:
            logger.debug("artifact_watcher._watch_loop cancelled session_id={}", session_id)
        except OSError as exc:
            logger.error("artifact_watcher._watch_loop fs error session_id={}: {}", session_id, exc)

    async def _debounced_version(
        self, session_id: UUID, name: str, fs_path: Path, debounce_key: str
    ) -> None:
        await asyncio.sleep(_DEBOUNCE_MS / 1000.0)
        self._debounce_tasks.pop(debounce_key, None)
        await self.version_file(session_id, name, fs_path)

    async def _handle_deletion(self, session_id: UUID, name: str) -> None:
        logger.debug("artifact_watcher._handle_deletion session_id={} name={}", session_id, name)
        artifacts = await self._storage.list_artifacts(session_id)
        artifact = next((a for a in artifacts if a.name == name), None)
        if artifact is None:
            return

        await self._storage.mark_artifact_deleted(artifact.id)

        await self._storage.append_permission(
            session_id=session_id,
            task_id=None,
            tool_name="fs_delete",
            decision=PermissionDecision.DELETED_OBSERVED,
            reason=f"File deleted: {name}",
            input_data={},
        )

        if self._publish is not None:
            self._publish(
                Topic.ARTIFACT,
                {
                    "type": "artifact.deleted",
                    "session_id": str(session_id),
                    "artifact_id": str(artifact.id),
                    "name": name,
                },
            )

        cache_key = f"{session_id}:{name}"
        self._hashes.pop(cache_key, None)
