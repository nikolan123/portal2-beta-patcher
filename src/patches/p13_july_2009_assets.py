"""
Patch 13: Supply 852_1 with the 852_0 tempcontent
"""
from __future__ import annotations

from pathlib import Path
import shutil

from extractor import extract_revision_chain
from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent, RevisionInput
from patches.base import PatchError, sha256_file
from patches.p12_july_2010_assets import CONTENT_FOLDER


SOURCE_BLOB_SHA256 = "3a6ea6546058bfe1a396d5167a869f626e26b9118eee9c95594d08e2b87c169f"
SOURCE_DAT_SHA256 = "ae227e4c03f23bf10cd2dc3032dd5007c699f761aec9acc63989a95787f22276"
def source_revision(context: PatchContext) -> RevisionInput:
    matches = {}
    for chain in context.supplemental_revision_chains:
        if not chain:
            continue
        revision = chain[0]
        if (
            (revision.depot_id, revision.version) == (852, 0)
            and revision.blob_sha256 == SOURCE_BLOB_SHA256
            and revision.dat_sha256 == SOURCE_DAT_SHA256
        ):
            matches[(revision.blob_path, revision.dat_path)] = revision
    if len(matches) != 1:
        raise PatchError("The verified July 2009 852_0 archives were not supplied")
    return next(iter(matches.values()))


def overlay_tree(source: Path, destination: Path, context: PatchContext, progress: ProgressCallback) -> None:
    files = [path for path in source.rglob("*") if path.is_file()]
    for index, source_file in enumerate(files, start=1):
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        destination_file = destination / source_file.relative_to(source)
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        progress(ProgressEvent("p13", index, max(len(files), 1), "Overlaying July 2009 assets"))


class July2009AssetsPatch:
    id = "p13"
    display_name = "July 2009 Assets"
    description = "Copy required assets from July 2009 852_0. Game will not launch without this."

    def _destination(self, context: PatchContext) -> Path:
        return context.root / CONTENT_FOLDER

    def check(self, context: PatchContext) -> bool:
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        revision = source_revision(context)
        progress(ProgressEvent(self.id, 0, 2, "Checking the July 2009 852_0 archives"))
        blob_hash = sha256_file(revision.blob_path)
        dat_hash = sha256_file(revision.dat_path)
        if blob_hash != SOURCE_BLOB_SHA256 or dat_hash != SOURCE_DAT_SHA256:
            raise PatchError("The July 2009 852_0 archives failed SHA-256 verification")
        context.report.input_hashes["support:852:0:blob"] = blob_hash
        context.report.input_hashes["support:852:0:dat"] = dat_hash

        temporary = context.root / ".p13-852_0-assets.partial"
        destination = self._destination(context)
        if temporary.exists():
            raise PatchError("A temporary July 2009 extraction folder already exists")
        try:
            extract_revision_chain(
                (revision,), temporary, progress, context.cancel_event, include_prefixes=(CONTENT_FOLDER,)
            )
            source = temporary / CONTENT_FOLDER
            if not source.is_dir():
                raise PatchError("The 852_0 archive did not produce portal2_tempcontent")
            if destination.exists():
                overlay_tree(source, destination, context, progress)
            else:
                source.replace(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
        progress(ProgressEvent(self.id, 2, 2, "Installed the July 2009 assets"))

    def verify(self, context: PatchContext) -> None:
        destination = self._destination(context)
        if not destination.is_dir():
            raise PatchError("portal2_tempcontent was not installed")
