"""
Patch 8: install the small set of additional prerelease runtime assets.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

from models import PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file


ARCHIVE_NAME = "p8_prerelease_assets.zip"
ARCHIVE_SHA256 = "aab8f60bb903c34f193fafbbe89e2ba46b3993b05bbb63aa6d504690146fb4c3"
ASSET_HASHES = {
    "portal/materials/props_animsign/signage_num00_frame.vmt": "a22dc260a67e35f8c1ab25781194490b41602bd2e93856b3303201eb217380e3",
    "portal/materials/props_animsign/signage_num00_frame.vtf": "b3ebcd4ab209c9f56e95499f02ce3eded0df7801d1a6e8203ec1588cff7086ce",
    "portal2/materials/effects/huntertracer.vmt": "6bc01bcf739440101d22743776b08e646a3de7ff2cb198008738f7dc94499288",
    "portal2/materials/effects/huntertracer.vtf": "a9468b5b33ead34e6c825a7f28bb94922a2459baf71c1ac20a1dfe71bfead8f0",
    "portal2/particles/achievement.pcf": "fc692170bb6c7eb80f8f8e334c2ab848b6bfd760abf1b09eb96189f656f51d9e",
}
ACHIEVEMENT_PATH = "particles/achievement.pcf"


def archive_path() -> Path:
    return Path(__file__).with_name(ARCHIVE_NAME)


def add_achievement_to_manifest(data: bytes) -> bytes:
    if ACHIEVEMENT_PATH.encode("ascii") in data:
        return data

    newline = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.splitlines(keepends=True)
    entry = b'\t"file"\t\t"particles/achievement.pcf"' + newline

    for index, line in enumerate(lines):
        if b"particles/airvents.pcf" in line:
            lines.insert(index, entry)
            return b"".join(lines)

    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == b"}":
            lines.insert(index, entry)
            return b"".join(lines)

    raise PatchError("The particle manifest has an unexpected format")


class PrereleaseAssetsPatch:
    id = "p8"
    display_name = "Additional prerelease assets"
    description = "Install the missing achievement particle, hunter tracer, and animated sign assets."

    def _manifest(self, context: PatchContext) -> Path:
        return context.root / "portal2" / "particles" / "particles_manifest.txt"

    def check(self, context: PatchContext) -> bool:
        for relative, expected_hash in ASSET_HASHES.items():
            target = context.root.joinpath(*relative.split("/"))
            if not target.is_file() or sha256_file(target) != expected_hash:
                return True
        manifest = self._manifest(context)
        return not manifest.is_file() or ACHIEVEMENT_PATH.encode("ascii") not in manifest.read_bytes()

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        bundle = archive_path()
        if not bundle.is_file() or sha256_file(bundle) != ARCHIVE_SHA256:
            raise PatchError("The bundled prerelease asset archive is missing or damaged")

        with ZipFile(bundle) as archive:
            if set(archive.namelist()) != set(ASSET_HASHES):
                raise PatchError("The bundled prerelease asset archive contains unexpected files")

            total = len(ASSET_HASHES) + 1
            for index, (relative, expected_hash) in enumerate(ASSET_HASHES.items(), start=1):
                payload = archive.read(relative)
                if hashlib.sha256(payload).hexdigest() != expected_hash:
                    raise PatchError(f"Bundled prerelease asset failed verification: {relative}")

                target = context.root.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.read_bytes() != payload:
                    backup_file(target, target.name + ".original.bak", context)
                if not target.exists() or target.read_bytes() != payload:
                    atomic_write(target, payload)
                progress(ProgressEvent("p8", index, total, f"Installing {relative}"))

        manifest = self._manifest(context)
        if not manifest.is_file():
            raise PatchError("The Portal 2 particle manifest is missing")
        original = manifest.read_bytes()
        updated = add_achievement_to_manifest(original)
        if updated != original:
            backup_file(manifest, "particles_manifest.original.bak", context)
            atomic_write(manifest, updated)
        progress(ProgressEvent("p8", total, total, "Registering the achievement particle"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("Additional prerelease assets verification failed")
