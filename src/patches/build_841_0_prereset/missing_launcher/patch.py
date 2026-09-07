"""Add the missing hl2.exe."""
from __future__ import annotations

from pathlib import Path

from patches.resources import resource_path
from patches.definitions import PatchDefinition, Resource
from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, sha256_file


LAUNCHER_NAME = "hl2.exe"
LAUNCHER_SHA256 = "ac7095e796cf08388d271f48f11c3b92de6bff59bf4d1f144a7842170c7b65c2"


def launcher_path() -> Path:
    return resource_path(Resource("build_841_0_prereset/missing_launcher", LAUNCHER_NAME))


def read_launcher() -> bytes:
    source = launcher_path()
    if not source.is_file() or sha256_file(source) != LAUNCHER_SHA256:
        raise PatchError("The bundled hl2.exe is missing or damaged")
    return source.read_bytes()


class Hl2LauncherPatch:
    id = "841_0_prereset.missing_launcher"
    display_name = "Missing hl2.exe fix"
    description = "Add the missing hl2.exe needed to run this build."

    def _destination(self, context: PatchContext) -> Path:
        return context.root / "hl2.exe"

    def check(self, context: PatchContext) -> bool:
        read_launcher()
        destination = self._destination(context)
        if not destination.exists():
            return True
        if destination.is_file() and sha256_file(destination) == LAUNCHER_SHA256:
            return False
        raise PatchError("Refusing to replace an unexpected hl2.exe in the output")

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        progress(ProgressEvent(self.id, 0, 1, f"Installing the {self.display_name}"))
        atomic_write(self._destination(context), read_launcher())
        progress(ProgressEvent(self.id, 1, 1, f"Installed the {self.display_name}"))

    def verify(self, context: PatchContext) -> None:
        destination = self._destination(context)
        if not destination.is_file() or sha256_file(destination) != LAUNCHER_SHA256:
            raise PatchError("The hl2.exe fix failed verification")



DEFINITION = PatchDefinition(Hl2LauncherPatch(), capabilities=frozenset({"provides_hl2_exe"}), resources=(Resource('build_841_0_prereset/missing_launcher', 'hl2.exe', native=False),))
