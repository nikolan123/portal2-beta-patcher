"""
Patch 1: Copy assets from Half-Life 2
This patch extracts the supplied hl2 install's assets from vpk files and copies them over to portal.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from models import BuildCancelled
from models import PatchContext, ProgressEvent, ProgressCallback
from steam import relevant_hl2_vpks
from vpk import VPKArchive, safe_relative_path


ASSET_MARKER = "p1-curated-v2\n"

def load_asset_allowlist() -> frozenset[str]:
    path = Path(__file__).with_name("p1_hl2_assets.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().casefold() for line in lines if line.strip() and not line.startswith("#"))


HL2_ASSET_ALLOWLIST = load_asset_allowlist()


def copy_loose_hl2_scripts(source, destination, cancel_event, progress):
    """Copy a loose directory without overwriting files already present."""
    files = sorted(path for path in source.rglob("*") if path.is_file())
    written = skipped = byte_count = 0
    for index, path in enumerate(files, start=1):
        if cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        relative = path.relative_to(source)
        target = destination / relative
        if target.exists():
            skipped += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            written += 1
            byte_count += path.stat().st_size
        if index == 1 or index == len(files) or index % 25 == 0:
            progress(index, max(len(files), 1), relative.as_posix())
    return written, skipped, byte_count, len(files)


def selected_vpk_entries(archives):
    """Return allowlisted entries once, preferring the first VPK that has one."""
    selected = []
    seen = set()
    for archive_path, archive in archives:
        for entry in archive.entries:
            key = entry.path.casefold()
            if key in HL2_ASSET_ALLOWLIST and key not in seen:
                selected.append((archive_path, archive, entry))
                seen.add(key)
    return selected, seen


def copy_selected_vpk_assets(selected, destination, cancel_event, progress):
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
                    "p1",
                    index,
                    max(total, 1),
                    f"{archive_path.name}: {entry.path}",
                )
            )
    return written, skipped, byte_count


def copy_selected_loose_assets(source, destination, selected_paths, cancel_event, progress):
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
            progress(ProgressEvent("p1", index, max(total, 1), f"HL2 loose file: {relative}"))
    return written, skipped, byte_count, total


class Hl2AssetsPatch:
    id = "p1"
    display_name = "Half-Life 2 assets"

    def _marker(self, context: PatchContext):
        return context.root / "hl2" / ".p2patcher-assets-complete"

    def check(self, context: PatchContext) -> bool:
        marker = self._marker(context)
        return not marker.is_file() or marker.read_text(encoding="ascii", errors="replace") != ASSET_MARKER

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        archive_paths = relevant_hl2_vpks(context.hl2_source)
        archives = [(path, VPKArchive(path)) for path in archive_paths]
        destination = context.root / "hl2"
        destination.mkdir(parents=True, exist_ok=True)

        selected, found_in_vpks = selected_vpk_entries(archives)
        written, skipped, byte_count = copy_selected_vpk_assets(
            selected,
            destination,
            context.cancel_event,
            progress,
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

        remaining = HL2_ASSET_ALLOWLIST - found_in_vpks
        written, skipped, byte_count, file_count = copy_selected_loose_assets(
            context.hl2_source / "hl2",
            destination,
            remaining,
            context.cancel_event,
            progress,
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

        self._marker(context).write_text(ASSET_MARKER, encoding="ascii")

    def verify(self, context: PatchContext) -> None:
        marker = self._marker(context)
        if not marker.is_file() or marker.read_text(encoding="ascii", errors="replace") != ASSET_MARKER:
            raise RuntimeError("HL2 asset extraction did not complete")
        if not context.report.hl2_archives:
            raise RuntimeError("HL2 asset extraction produced no report")
