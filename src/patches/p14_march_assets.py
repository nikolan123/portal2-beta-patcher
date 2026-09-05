"""
Patch 14: Install missing assets for the March builds
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file


ARCHIVE_NAME = "p14_march_assets.zip"
ARCHIVE_SHA256 = "29e5f56e4418f10d7ce00a2a4cf9c77cbf5ef38dd7d9d0d3e329ce7d603dd472"
ALLOWED_ROOTS = {"portal", "portal2", "portal2_tempcontent"}


def archive_path() -> Path:
    return Path(__file__).with_name(ARCHIVE_NAME)


def read_bundle() -> dict[str, bytes]:
    bundle = archive_path()
    if not bundle.is_file() or sha256_file(bundle) != ARCHIVE_SHA256:
        raise PatchError("The bundled March asset archive is missing or damaged")

    assets: dict[str, bytes] = {}
    with ZipFile(bundle) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw_name = info.filename
            path = PurePosixPath(raw_name)
            if (
                "\\" in raw_name
                or path.is_absolute()
                or not path.parts
                or ".." in path.parts
                or path.parts[0] not in ALLOWED_ROOTS
            ):
                raise PatchError(f"Unsafe path in the bundled March assets: {raw_name}")
            normalized = path.as_posix()
            if normalized in assets:
                raise PatchError(f"Duplicate path in the bundled March assets: {normalized}")
            assets[normalized] = archive.read(info)
    if not assets:
        raise PatchError("The bundled March asset archive is empty")
    return assets


class MarchAssetsPatch:
    id = "p14"
    display_name = "March extra assets"
    description = "Install some missing materials and models used by the March 2010 builds."

    def check(self, context: PatchContext) -> bool:
        for relative, payload in read_bundle().items():
            target = context.root.joinpath(*PurePosixPath(relative).parts)
            if not target.is_file() or sha256_file(target) != hashlib.sha256(payload).hexdigest():
                return True
        return False

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        assets = read_bundle()
        total = len(assets)
        for index, (relative, payload) in enumerate(assets.items(), start=1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            target = context.root.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != payload:
                backup_file(target, target.name + ".original.bak", context)
            if not target.exists() or target.read_bytes() != payload:
                atomic_write(target, payload)
            progress(ProgressEvent(self.id, index, total, f"Installing {relative}"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("March build asset verification failed")
