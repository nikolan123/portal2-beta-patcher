"""Patch 10: Install the Goldberg Steam emulator"""
from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file


ARCHIVE_SHA256 = "8465984b01b42a75f5faea8f2d884bbd6085a695c40c2b90eb0385f0a5081266"
MAX_ARCHIVE_SIZE = 32 * 1024 * 1024
ARCHIVE_FILES = (
    "steam_api.dll",
    "tools/generate_interfaces_file.exe",
)


def read_goldberg_archive(path: Path) -> dict[str, bytes]:
    if path.stat().st_size > MAX_ARCHIVE_SIZE:
        raise PatchError("The Goldberg ZIP is unexpectedly large")
    if sha256_file(path) != ARCHIVE_SHA256:
        raise PatchError(
            "The Goldberg ZIP does not match the supported release "
            f"(expected SHA-256 {ARCHIVE_SHA256})"
        )
    try:
        with ZipFile(path) as archive:
            return {name: archive.read(name) for name in ARCHIVE_FILES}
    except (BadZipFile, KeyError) as error:
        raise PatchError("The Goldberg ZIP is invalid or incomplete") from error


def generate_interfaces(generator: bytes, original_api: bytes) -> bytes:
    with TemporaryDirectory(prefix="portal2-goldberg-") as temporary:
        folder = Path(temporary)
        generator_path = folder / "generate_interfaces_file.exe"
        api_path = folder / "steam_api.dll"
        generator_path.write_bytes(generator)
        api_path.write_bytes(original_api)
        result = subprocess.run(
            [generator_path, api_path],
            cwd=folder,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = folder / "steam_interfaces.txt"
        if result.returncode != 0 or not output.is_file() or not output.stat().st_size:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise PatchError(f"Could not generate steam_interfaces.txt{': ' + detail if detail else ''}")
        return output.read_bytes()


def steam_api_targets(root: Path) -> tuple[Path, ...]:
    return tuple(path for path in (root / "steam_api.dll", root / "bin" / "steam_api.dll") if path.is_file())


class GoldbergPatch:
    id = "p10"
    display_name = "Goldberg emulator"
    description = (
        "Use a supplied Goldberg ZIP to fix main menu and partial multiplayer functionality in certain builds."
    )

    def check(self, context: PatchContext) -> bool:
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        if context.cancel_event.is_set():
            raise BuildCancelled("Build cancelled")
        if context.goldberg_archive is None:
            raise PatchError("Select the Goldberg ZIP to use")
        progress(ProgressEvent(self.id, 0, 3, "Verifying the Goldberg ZIP"))
        files = read_goldberg_archive(context.goldberg_archive)
        replacement = files["steam_api.dll"]
        targets = steam_api_targets(context.root)
        if not targets:
            raise PatchError("This build does not contain a 32-bit steam_api.dll")

        progress(ProgressEvent(self.id, 1, 3, "Backing up the original Steam API"))
        interface_payloads: dict[Path, bytes] = {}
        for target in targets:
            backup = target.with_name("steam_api.original.bak")
            if target.read_bytes() == replacement:
                if not backup.is_file():
                    raise PatchError(f"Cannot make {target.name} reversible because its original is missing")
            else:
                backup_file(target, backup.name, context)
            original_api = backup.read_bytes()
            interface_payloads[target.parent / "steam_interfaces.txt"] = generate_interfaces(
                files["tools/generate_interfaces_file.exe"], original_api
            )

        progress(ProgressEvent(self.id, 2, 3, "Installing offline compatibility files"))
        for target in targets:
            interface = target.parent / "steam_interfaces.txt"
            if interface.is_file():
                backup_file(interface, "steam_interfaces.original.bak", context)
            atomic_write(target, replacement)
            atomic_write(interface, interface_payloads[interface])

        progress(ProgressEvent(self.id, 3, 3, "Installed Goldberg compatibility"))

    def verify(self, context: PatchContext) -> None:
        if context.goldberg_archive is None:
            raise PatchError("Goldberg ZIP is unavailable for verification")
        replacement = read_goldberg_archive(context.goldberg_archive)["steam_api.dll"]
        targets = steam_api_targets(context.root)
        if not targets or any(target.read_bytes() != replacement for target in targets):
            raise PatchError("Goldberg Steam API installation failed verification")
        for target in targets:
            if not target.with_name("steam_api.original.bak").is_file():
                raise PatchError("An original Steam API backup is missing")
            if not (target.parent / "steam_interfaces.txt").is_file():
                raise PatchError("steam_interfaces.txt is missing")
