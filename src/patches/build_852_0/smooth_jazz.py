"""Remove the Smooth Jazz from Smooth Jazz lines."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import struct

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition


VOICE_DIRECTORY = Path("portal2_tempcontent/sound/vo/glados")


@dataclass(frozen=True)
class VoiceCue:
    filename: str
    cut_seconds: int
    original_sha256: str
    patched_sha256: str


CUES = (
    VoiceCue(
        "prehub42.wav",
        12,
        "15eca5ebdf213d86a9801dd888b457830452606027526aac544e4fe18c5b8258",
        "b2a8146941f940b62cef60f5b15a223d74f09fc9719a02723fa627989e5363bb",
    ),
    VoiceCue(
        "prehub44.wav",
        7,
        "fc74eba0d50a6c22456f63300898a8847d4c73435a7ceebab6238bd8d0e0626a",
        "afb135b367831c39fa032b12404db11d53e9ea3b359356a6a227fd2335ea3c6e",
    ),
)


def trim_smooth_jazz(data: bytes, cut_seconds: int) -> bytes:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise PatchError("PreHub42.wav is not a valid RIFF WAVE file")
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise PatchError("PreHub42.wav has an unexpected RIFF size")
    if data[12:16] != b"fmt " or struct.unpack_from("<I", data, 16)[0] != 16:
        raise PatchError("PreHub42.wav has an unexpected format chunk")

    audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack_from(
        "<HHIIHH", data, 20
    )
    if (audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample) != (
        1,
        1,
        44100,
        88200,
        2,
        16,
    ):
        raise PatchError("PreHub42.wav does not have the expected PCM format")
    if data[36:40] != b"data" or struct.unpack_from("<I", data, 40)[0] != len(data) - 44:
        raise PatchError("PreHub42.wav has an unexpected data chunk")

    kept_data_size = cut_seconds * byte_rate
    if len(data) - 44 < kept_data_size:
        raise PatchError("PreHub42.wav is shorter than the requested cut point")

    trimmed = bytearray(data[:44 + kept_data_size])
    struct.pack_into("<I", trimmed, 4, len(trimmed) - 8)
    struct.pack_into("<I", trimmed, 40, kept_data_size)
    return bytes(trimmed)


def sound_path(root: Path, cue: VoiceCue) -> Path:
    relative_path = VOICE_DIRECTORY / cue.filename
    candidates = (root / relative_path, root / "game" / relative_path)
    existing = tuple(path for path in candidates if path.is_file())
    if not existing:
        raise PatchError(f"852_0 {cue.filename} is missing")
    if len(existing) != 1:
        raise PatchError(f"Found more than one 852_0 {cue.filename}")
    return existing[0]


class SmoothJazzPatch:
    id = "852_0.smooth_jazz"
    display_name = "Remove copyrighted Smooth Jazz"
    description = "Remove the Smooth Jazz from Smooth Jazz lines."

    def check(self, context: PatchContext) -> bool:
        needs_patch = False
        for cue in CUES:
            current_hash = sha256_file(sound_path(context.root, cue))
            if current_hash == cue.original_sha256:
                needs_patch = True
            elif current_hash != cue.patched_sha256:
                raise PatchError(f"Refusing to patch unknown {cue.filename} ({current_hash})")
        return needs_patch

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        for index, cue in enumerate(CUES):
            if context.cancel_event.is_set():
                raise BuildCancelled("Build cancelled")
            progress(ProgressEvent(self.id, index, len(CUES), f"Trimming {cue.filename}"))
            path = sound_path(context.root, cue)
            current_hash = sha256_file(path)
            if current_hash == cue.patched_sha256:
                continue
            if current_hash != cue.original_sha256:
                raise PatchError(f"{cue.filename} changed before it could be patched")

            original = path.read_bytes()
            backup_file(path, f"{path.stem}.original.bak", context)
            patched = trim_smooth_jazz(original, cue.cut_seconds)
            if sha256(patched).hexdigest() != cue.patched_sha256:
                raise PatchError(f"Internal {cue.filename} verification failed")
            atomic_write(path, patched)
        progress(ProgressEvent(self.id, len(CUES), len(CUES), "Removed the Smooth Jazz music tails"))

    def verify(self, context: PatchContext) -> None:
        for cue in CUES:
            if sha256_file(sound_path(context.root, cue)) != cue.patched_sha256:
                raise PatchError(f"{cue.filename} Smooth Jazz patch failed verification")


DEFINITION = PatchDefinition(SmoothJazzPatch(), default_selected=False)
