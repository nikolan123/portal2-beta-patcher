"""Retail HL2 copying"""
from __future__ import annotations

import shutil
from pathlib import Path

from models import BuildCancelled, PatchContext, ProgressEvent, ProgressCallback
from patches.base import PatchError, atomic_write
from patches.definitions import Resource
from patches.resources import resource_path
from steam import relevant_hl2_vpks
from vpk import VPKArchive, safe_relative_path


def load_asset_allowlist(resource: Resource) -> frozenset[str]:
    lines = resource_path(resource).read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().casefold()
        for line in lines
        if line.strip() and not line.startswith("#")
    )


def selected_vpk_entries(archives, allowlist):
    """Return allowlisted entries once, preferring the first VPK that has one."""
    selected = []
    seen = set()
    for archive_path, archive in archives:
        for entry in archive.entries:
            key = entry.path.casefold()
            if key in allowlist and key not in seen:
                selected.append((archive_path, archive, entry))
                seen.add(key)
    return selected, seen


def copy_selected_vpk_assets(selected, destination, cancel_event, progress, patch_id):
    written = skipped = byte_count = 0
    total = len(selected)
    for index, (archive_path, archive, entry) in enumerate(selected, start=1):
        if cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        relative = safe_relative_path(entry.path)
        target = destination.joinpath(*relative.parts)
        if target.exists():
            skipped += 1
        else:
            payload = archive.read_entry(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            written += 1
            byte_count += len(payload)
        if index == 1 or index == total or index % 25 == 0:
            progress(
                ProgressEvent(
                    patch_id,
                    index,
                    max(total, 1),
                    f"{archive_path.name}: {entry.path}",
                )
            )
    return written, skipped, byte_count


def copy_selected_loose_assets(source, destination, selected_paths, cancel_event, progress, patch_id):
    available = []
    for relative in sorted(selected_paths):
        path = source.joinpath(*relative.split("/"))
        if path.is_file():
            available.append((relative, path))

    written = skipped = byte_count = 0
    total = len(available)
    for index, (relative, path) in enumerate(available, start=1):
        if cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        target = destination.joinpath(*relative.split("/"))
        if target.exists():
            skipped += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            written += 1
            byte_count += path.stat().st_size
        if index == 1 or index == total or index % 25 == 0:
            progress(ProgressEvent(patch_id, index, max(total, 1), f"HL2 loose file: {relative}"))
    return written, skipped, byte_count, total


class CuratedHl2AssetsPatch:
    id: str
    display_name: str
    description: str
    allowlist: frozenset[str]
    asset_marker: str
    require_all_assets: bool = True

    def _asset_folder(self, context: PatchContext):
        return context.root / "hl2"

    def _source_archives(self, source: Path):
        return relevant_hl2_vpks(source)

    def _marker(self, context: PatchContext):
        return self._asset_folder(context) / ".p2patcher-assets-complete"

    def check(self, context: PatchContext) -> bool:
        marker = self._marker(context)
        return (
            not marker.is_file()
            or marker.read_text(encoding="ascii", errors="replace") != self.asset_marker
            or (self.require_all_assets and bool(self._missing_assets(context)))
        )

    def _missing_assets(self, context: PatchContext) -> list[str]:
        destination = self._asset_folder(context)
        return sorted(path for path in self.allowlist if not (destination / path).is_file())

    def _verify_assets(self, context: PatchContext) -> None:
        if not self.require_all_assets:
            return
        missing = self._missing_assets(context)
        if missing:
            raise PatchError("Required HL2 assets are missing: " + ", ".join(missing))

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.hl2_source is None:
            raise RuntimeError("Half-Life 2 is required for this fix")
        archive_paths = self._source_archives(context.hl2_source)
        archives = [(path, VPKArchive(path)) for path in archive_paths]
        destination = self._asset_folder(context)
        destination.mkdir(parents=True, exist_ok=True)

        selected, found_in_vpks = selected_vpk_entries(archives, self.allowlist)
        written, skipped, byte_count = copy_selected_vpk_assets(
            selected,
            destination,
            context.cancel_event,
            progress,
            self.id,
        )
        context.report.hl2_archives.append(
            {
                "archive": "selected HL2 VPK assets",
                "entries": len(selected),
                "written": written,
                "skipped_conflicts": skipped,
                "bytes": byte_count,
            }
        )

        remaining = self.allowlist - found_in_vpks
        written, skipped, byte_count, file_count = copy_selected_loose_assets(
            context.hl2_source / "hl2",
            destination,
            remaining,
            context.cancel_event,
            progress,
            self.id,
        )
        context.report.hl2_archives.append(
            {
                "archive": str(context.hl2_source / "hl2"),
                "entries": file_count,
                "written": written,
                "skipped_conflicts": skipped,
                "bytes": byte_count,
            }
        )

        self._verify_assets(context)
        atomic_write(self._marker(context), self.asset_marker.encode("ascii"))

    def verify(self, context: PatchContext) -> None:
        marker = self._marker(context)
        if not marker.is_file() or marker.read_text(encoding="ascii", errors="replace") != self.asset_marker:
            raise RuntimeError("HL2 asset extraction did not complete")
        self._verify_assets(context)
