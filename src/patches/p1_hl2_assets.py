"""
Patch 1: Copy assets from Half-Life 2
This patch extracts the supplied hl2 install's assets from vpk files and copies them over to portal.
TODO: limit this to only extract used files
"""
from __future__ import annotations

import shutil

from models import BuildCancelled
from models import PatchContext, ProgressEvent, ProgressCallback
from steam import relevant_hl2_vpks
from vpk import VPKArchive


def copy_loose_hl2_scripts(source, destination, cancel_event, progress):
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


class Hl2AssetsPatch:
    id = "p1"
    display_name = "Half-Life 2 assets"

    def check(self, context: PatchContext) -> bool:
        return not (context.root / "hl2" / ".p2patcher-assets-complete").is_file()

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        archive_paths = relevant_hl2_vpks(context.hl2_source)
        archives = [(path, VPKArchive(path)) for path in archive_paths]
        total_entries = sum(len(archive.entries) for _path, archive in archives)
        completed_entries = 0
        destination = context.root / "hl2"
        for archive_path, archive in archives:
            base_completed = completed_entries

            def update(current: int, _count: int, entry: str) -> None:
                progress(
                    ProgressEvent(
                        self.id,
                        base_completed + current,
                        max(total_entries, 1),
                        f"{archive_path.name}: {entry}",
                    )
                )

            written, skipped, byte_count = archive.extract_to(destination, context.cancel_event, update)
            completed_entries += len(archive.entries)
            context.report.hl2_archives.append(
                {
                    "archive": str(archive_path),
                    "entries": len(archive.entries),
                    "written": written,
                    "skipped_conflicts": skipped,
                    "bytes": byte_count,
                }
            )
            progress(ProgressEvent(self.id, completed_entries, max(total_entries, 1), f"Extracted {archive_path.name}"))

        loose_source = context.hl2_source / "hl2" / "scripts"
        if not loose_source.is_dir():
            raise RuntimeError("The Half-Life 2 scripts folder is missing")
        loose_destination = destination / "scripts"

        def update_loose(current: int, count: int, entry: str) -> None:
            progress(ProgressEvent(self.id, current, count, f"HL2 scripts: {entry}"))

        written, skipped, byte_count, file_count = copy_loose_hl2_scripts(
            loose_source,
            loose_destination,
            context.cancel_event,
            update_loose,
        )
        context.report.hl2_archives.append(
            {
                "archive": str(loose_source),
                "entries": file_count,
                "written": written,
                "skipped_conflicts": skipped,
                "bytes": byte_count,
            }
        )
        (destination / ".p2patcher-assets-complete").write_text("p1\n", encoding="ascii")

    def verify(self, context: PatchContext) -> None:
        marker = context.root / "hl2" / ".p2patcher-assets-complete"
        if not marker.is_file() or not context.report.hl2_archives:
            raise RuntimeError("HL2 asset extraction did not complete")
