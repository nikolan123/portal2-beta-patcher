"""
install the bundled Source Thread Fix game wrapper.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from patches.resources import resource_path
from patches.definitions import PatchDefinition, Resource
from models import BuildCancelled, PatchContext, ProgressEvent, ProgressCallback
from patches.base import atomic_write, backup_file, sha256_file


FILES = {
    "hl2.wrap.exe": "701b84b1df352139acd6c518a206f1d37a55e07aa8ad44479b69d290434c0ab9",
    "LICENCE-threadfix": None,
}


def bundled_path(name: str) -> Path:
    return resource_path(Resource("generic/thread_fix", "LICENCE" if name == "LICENCE-threadfix" else name))


def destination_path(context: PatchContext, name: str) -> Path:
    if name == "LICENCE-threadfix":
        return context.root / ".p2patcher" / name
    return context.root / name


def read_bundled_files() -> dict[str, bytes]:
    files = {}
    for name, expected_hash in FILES.items():
        path = bundled_path(name)
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Bundled Source Thread Fix file is missing: {name}") from error
        if expected_hash is not None and sha256(payload).hexdigest() != expected_hash:
            raise RuntimeError(f"Bundled Source Thread Fix file failed SHA-256 verification: {name}")
        files[name] = payload
    return files


class ThreadFixPatch:
    id = "thread_fix"
    display_name = "Source Thread Fix"
    description = "Install the Source Thread Fix wrapper for CPUs with more threads than this engine supports."

    def check(self, context: PatchContext) -> bool:
        return any(
            not destination_path(context, name).is_file()
            or (expected_hash is not None and sha256_file(destination_path(context, name)) != expected_hash)
            for name, expected_hash in FILES.items()
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")

        progress(ProgressEvent(self.id, 0, 1, "Installing Source Thread Fix v1.3"))
        files = read_bundled_files()
        for name, payload in files.items():
            destination = destination_path(context, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != payload:
                backup_file(destination, destination.name + ".original.bak", context)
            atomic_write(destination, payload)
        progress(ProgressEvent(self.id, 1, 1, "Installed Source Thread Fix v1.3"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Source Thread Fix installation failed verification")



DEFINITION = PatchDefinition(ThreadFixPatch(), resources=(Resource('generic/thread_fix', 'hl2.wrap.exe', native=False), Resource('generic/thread_fix', 'LICENCE', native=False),))
