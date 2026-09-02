"""
Patch 5: Install the Source Thread Fix game wrapper
This downloads some guy's source engine thread fixer and applies it. Hashes are compared to make sure the file is as expected
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from models import BuildCancelled, PatchContext, ProgressEvent, ProgressCallback
from patches.base import atomic_write, backup_file, sha256_file


DOWNLOAD_URL = "https://dl.mikes.software/sourcethreadfix/threadfix-v1.3-win32.zip"
ARCHIVE_SHA256 = "b2b50a74edaf9d12d0ea01162987ed797fdfac4654360845afd61a3b99a99120"
MAX_DOWNLOAD_SIZE = 1024 * 1024
FILES = {
    "hl2.wrap.exe": "701b84b1df352139acd6c518a206f1d37a55e07aa8ad44479b69d290434c0ab9",
    "LICENCE-threadfix": "140477b3034645037d0da2f1cb36b6becc9d9f3a73388dadbee6c14c7cae9948",
}


def download_thread_fix() -> bytes:
    request = Request(DOWNLOAD_URL, headers={"User-Agent": "Portal2BetaPatcher/0.1"})
    with urlopen(request, timeout=30) as response:
        archive = response.read(MAX_DOWNLOAD_SIZE + 1)
    if len(archive) > MAX_DOWNLOAD_SIZE:
        raise RuntimeError("Source Thread Fix download is unexpectedly large")
    if sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("Source Thread Fix ZIP failed SHA-256 verification")
    return archive


def read_thread_fix_files(archive: bytes) -> dict[str, bytes]:
    try:
        with ZipFile(BytesIO(archive)) as zip_file:
            unexpected = set(zip_file.namelist()) - set(FILES)
            if unexpected:
                raise RuntimeError(f"Source Thread Fix ZIP has unexpected entries: {sorted(unexpected)}")
            extracted = {name: zip_file.read(name) for name in FILES}
    except (BadZipFile, KeyError) as error:
        raise RuntimeError("Source Thread Fix ZIP is invalid or incomplete") from error

    for name, expected_hash in FILES.items():
        if sha256(extracted[name]).hexdigest() != expected_hash:
            raise RuntimeError(f"Source Thread Fix file failed SHA-256 verification: {name}")
    return extracted


class ThreadFixPatch:
    id = "p5"
    display_name = "Source Thread Fix"

    def check(self, context: PatchContext) -> bool:
        return any(
            not (context.root / name).is_file()
            or sha256_file(context.root / name) != expected_hash
            for name, expected_hash in FILES.items()
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        progress(ProgressEvent(self.id, 0, 2, "Downloading Source Thread Fix v1.3"))
        try:
            archive = download_thread_fix()
        except OSError as error:
            raise RuntimeError(f"Could not download Source Thread Fix: {error}") from error

        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        progress(ProgressEvent(self.id, 1, 2, "Verifying Source Thread Fix"))
        extracted = read_thread_fix_files(archive)
        for name, payload in extracted.items():
            destination = context.root / name
            if destination.exists() and destination.read_bytes() != payload:
                backup_file(destination, destination.name + ".original.bak", context)
            atomic_write(destination, payload)
        progress(ProgressEvent(self.id, 2, 2, "Installed Source Thread Fix v1.3"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Source Thread Fix installation failed verification")
