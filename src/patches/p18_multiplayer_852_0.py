"""Patch 18: Install multiplayer runtime fixes for 852_0."""
from __future__ import annotations

from pathlib import Path

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file


ENGINE_SHA256 = "7e39efdf3907e5b25e8d20c124d03efaf226ecd6c408829b1c0a823d96bc0d8c"
SERVER_SHA256 = "1dc9c9ac0e12511b21beac4c183462df53b504920421e52e66e96e926659c948"

BUNDLED_FILES = {
    "d3d9.dll": "7c843006f81983617a37f57d7fb615d23bda99860b71ab745f2b0cea6ab00474",
    "dxwrapper.dll": "ec42e51cbb4408518d6348706557b18ef50a87485c8bfa1839c895123fa3295f",
    "dxwrapper.ini": None,
    "scripts/p2beta_multiplayer_852_0.asi": None,
}
_BUNDLE_NAMES = {
    "d3d9.dll": "asi_d3d9.dll",
    "dxwrapper.dll": "asi_dxwrapper.dll",
    "dxwrapper.ini": "asi_dxwrapper.ini",
    "scripts/p2beta_multiplayer_852_0.asi": "p18_multiplayer_852_0.asi",
}
def bundled_path(name: str) -> Path:
    packaged = Path(__file__).with_name(name)
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[2] / "build" / "native" / name


def runtime_root(context: PatchContext) -> Path:
    moved = context.root / "game"
    if (moved / "bin" / "engine.dll").is_file():
        return moved
    return context.root


def read_bundled_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for destination, expected_hash in BUNDLED_FILES.items():
        source = bundled_path(_BUNDLE_NAMES[destination])
        if (
            not source.is_file()
            or not source.stat().st_size
            or (expected_hash is not None and sha256_file(source) != expected_hash)
        ):
            raise PatchError(f"Bundled multiplayer patch file is missing or damaged: {source.name}")
        files[destination] = source.read_bytes()

    license_path = bundled_path("asi_LICENCE-dxwrapper.txt")
    if not license_path.is_file() or not license_path.stat().st_size:
        raise PatchError("Bundled DxWrapper license is missing or empty")
    files["LICENCE-dxwrapper.txt"] = license_path.read_bytes()
    return files


def destination_path(context: PatchContext, relative: str) -> Path:
    if relative == "LICENCE-dxwrapper.txt":
        return context.root / ".p2patcher" / relative
    return runtime_root(context) / "bin" / relative


class Multiplayer8520Patch:
    id = "p18"
    display_name = "Multiplayer fixes"
    description = "Repair multiplayer initialization, dialogue, and show real player names in co-op."

    def _validate_build(self, context: PatchContext) -> None:
        root = runtime_root(context)
        engine = root / "bin" / "engine.dll"
        server = root / "portal2" / "bin" / "server.dll"
        if not engine.is_file() or sha256_file(engine) != ENGINE_SHA256:
            raise PatchError("The multiplayer patch requires the known 852_0 engine.dll")
        if not server.is_file() or sha256_file(server) != SERVER_SHA256:
            raise PatchError("The multiplayer patch requires the known 852_0 server.dll")

    def check(self, context: PatchContext) -> bool:
        self._validate_build(context)
        return any(
            not destination_path(context, relative).is_file()
            or destination_path(context, relative).read_bytes() != payload
            for relative, payload in read_bundled_files().items()
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        self._validate_build(context)
        files = read_bundled_files()
        total = len(files)
        for index, (relative, payload) in enumerate(files.items(), start=1):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            destination = destination_path(context, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != payload:
                backup_file(destination, destination.name + ".original.bak", context)
            atomic_write(destination, payload)
            progress(ProgressEvent(self.id, index, total, f"Installed {destination.name}"))

    def verify(self, context: PatchContext) -> None:
        self._validate_build(context)
        for relative, payload in read_bundled_files().items():
            destination = destination_path(context, relative)
            if not destination.is_file() or destination.read_bytes() != payload:
                raise PatchError(f"Multiplayer patch failed verification: {destination.name}")
