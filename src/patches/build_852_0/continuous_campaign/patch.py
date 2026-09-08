"""
Install lumps that make a few changes for speedrun tools

- Changes the hub campaign launches from `map` to `changelevel`.
- Adds a marker to hub 6 that is removed when the ending starts so external tools can detect campaign completion.
- Unlocks slow time on entering catapult if the earlier upgrade was skipped.
"""
from __future__ import annotations

import struct
from pathlib import Path

from models import PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file, sha256_file
from patches.definitions import PatchDefinition, Resource
from patches.resources import resource_path


PACKAGE = "build_852_0/continuous_campaign"
LMP_HASHES = {
    "p2_lab_catapult_l_0.lmp": "aa1407b6335a10480b97ff0cb06af1926d5195120688f37510ace495edaad32f",
    "p2_lab_hub_1_l_0.lmp": "d05c697a2d7f75f9a08a3c6171ca8e4849be8e500286c8d23b67bf0db57b2eb6",
    "p2_lab_hub_2_l_0.lmp": "bcbc05de1b8ec76e35468a6c588e08fb90bc549b93f83dc2ebcccfd0676719d8",
    "p2_lab_hub_3_l_0.lmp": "add32b181ea565ad29107b3c2ea10026ca784e698f77abc4cc09095cec4a2795",
    "p2_lab_hub_4_l_0.lmp": "ed88d0c28433c48f2cdcbac4ca45148a23c92d9afb81f795aa0798f2813d1918",
    "p2_lab_hub_5_l_0.lmp": "9aae5a7b7dbf0ed1bc40bf43f5347d024e887e6912c2d54958273d95d58cc127",
    "p2_lab_hub_6_l_0.lmp": "79c30c036630db12f8dd3cd1118b2bcadff8846992ecac4b349c5f246ec49109",
    "p2_lab_prehub_2_l_0.lmp": "0de85aa02813f6361801f9b14dda8ca144d0039b2a6c649967c4ecda3c21af0a",
    "p2_lab_prehub_2a_l_0.lmp": "e4a48cf5245ae46657f171787bf20770be11ccb8329d65ac0d1777c012f7926a",
}


def bundled_path(name: str) -> Path:
    return resource_path(Resource(PACKAGE, name))


def destination_path(context: PatchContext, name: str) -> Path:
    return context.root / "portal2" / "maps" / name


def validate_lmp(name: str, data: bytes) -> None:
    if len(data) < 21:
        raise PatchError(f"Bundled campaign LMP is truncated: {name}")
    offset, lump_id, version, declared_length, map_revision = struct.unpack_from("<5i", data)
    if (offset, lump_id, version, map_revision) != (20, 0, 0, 0):
        raise PatchError(f"Bundled campaign LMP has an unexpected header: {name}")
    if declared_length != len(data) - offset or data[-1] != 0:
        raise PatchError(f"Bundled campaign LMP has an invalid entity payload: {name}")


def read_bundled_lmp(name: str) -> bytes:
    source = bundled_path(name)
    if not source.is_file() or sha256_file(source) != LMP_HASHES[name]:
        raise PatchError(f"Bundled campaign LMP is missing or damaged: {name}")
    data = source.read_bytes()
    validate_lmp(name, data)
    return data


class ContinuousCampaignPatch:
    id = "852_0.continuous_campaign"
    display_name = "Experimental speedrunning fixes"
    description = "Fixes for speedrun tools. Not recommended for normal play"

    def check(self, context: PatchContext) -> bool:
        for name, expected_hash in LMP_HASHES.items():
            read_bundled_lmp(name)
            destination = destination_path(context, name)
            if not destination.is_file() or sha256_file(destination) != expected_hash:
                return True
        return False

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        total = len(LMP_HASHES)
        for index, name in enumerate(LMP_HASHES, start=1):
            data = read_bundled_lmp(name)
            destination = destination_path(context, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.read_bytes() != data:
                backup_file(destination, name + ".before-continuous-campaign.bak", context)
            if not destination.is_file() or destination.read_bytes() != data:
                atomic_write(destination, data)
            progress(ProgressEvent(self.id, index, total, f"Installing {name}"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("Continuous campaign transition patch verification failed")


DEFINITION = PatchDefinition(
    ContinuousCampaignPatch(),
    default_selected=False,
    resources=tuple(Resource(PACKAGE, name) for name in LMP_HASHES),
)
