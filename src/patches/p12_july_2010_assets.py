"""
Patch 12: Supply 852_1 with the 852_2 tempcontent
"""
from __future__ import annotations

from pathlib import Path
import shutil

from extractor import extract_revision_chain
from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent, RevisionInput
from patches.base import PatchError, sha256_file


SOURCE_BLOB_SHA256 = "9b1b19edd62f2b03cdba4be3d4b58026185dc833a98666e9100f48e3eb46e2bd"
SOURCE_DAT_SHA256 = "b2cf29ea55a63308ab6f283f2aa9e2c613672cf291ad56cd182e30142869fe4f"
CONTENT_FOLDER = "portal2_tempcontent"


def source_chain(context: PatchContext) -> tuple[RevisionInput, ...]:
    matches = []
    for chain in context.supplemental_revision_chains:
        if not chain:
            continue
        final = chain[-1]
        if (
            (final.depot_id, final.version) == (852, 2)
            and final.blob_sha256 == SOURCE_BLOB_SHA256
            and final.dat_sha256 == SOURCE_DAT_SHA256
        ):
            matches.append(chain)
    if len(matches) != 1:
        raise PatchError("The verified July 2010 852_2 archive chain was not supplied")
    return matches[0]


class July2010AssetsPatch:
    id = "p12"
    display_name = "July 2010 Assets"
    description = "Copy extra assets from July 2010 852_2, including some dialogue."

    def _destination(self, context: PatchContext) -> Path:
        return context.root / CONTENT_FOLDER

    def check(self, context: PatchContext) -> bool:
        destination = self._destination(context)
        if not destination.exists():
            return True
        self.verify(context)
        return False

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        chain = source_chain(context)
        final = chain[-1]
        progress(ProgressEvent(self.id, 0, 2, "Checking the July 2010 852_2 archives"))
        blob_hash = sha256_file(final.blob_path)
        dat_hash = sha256_file(final.dat_path)
        if blob_hash != SOURCE_BLOB_SHA256 or dat_hash != SOURCE_DAT_SHA256:
            raise PatchError("The July 2010 852_2 archives failed SHA-256 verification")
        context.report.input_hashes["support:852:2:blob"] = blob_hash
        context.report.input_hashes["support:852:2:dat"] = dat_hash

        temporary = context.root / ".p12-852_2-assets.partial"
        destination = self._destination(context)
        if temporary.exists() or destination.exists():
            raise PatchError("Refusing to replace an existing portal2_tempcontent folder")
        try:
            progress(ProgressEvent(self.id, 1, 2, "Extracting portal2_tempcontent from 852_2"))
            extract_revision_chain(
                chain,
                temporary,
                progress,
                context.cancel_event,
                include_prefixes=(CONTENT_FOLDER,),
            )
            source = temporary / CONTENT_FOLDER
            if not source.is_dir():
                raise PatchError("The 852_2 archive did not produce portal2_tempcontent")
            source.replace(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
        progress(ProgressEvent(self.id, 2, 2, "Installed the July 2010 assets"))

    def verify(self, context: PatchContext) -> None:
        destination = self._destination(context)
        if not destination.is_dir():
            raise PatchError("portal2_tempcontent was not installed")
