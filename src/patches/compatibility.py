from patches.definitions import BuildProfile
from patches.registry import PATCH_COMPATIBILITY

def build_target(
    mode: str,
    depot_id: int | None,
    depot_version: int | None,
    depot_crc: int | None = None,
) -> tuple[int, int] | tuple[int, int, int]:
    if mode == "852_0":
        return (852, 0)
    if mode != "generic":
        raise ValueError(f"Unknown build mode: {mode}")
    if depot_id is None or depot_version is None:
        raise ValueError("Generic patch selection requires a depot ID and version")
    if depot_crc is not None:
        return (depot_id, depot_version, depot_crc)
    return (depot_id, depot_version)


def patch_set_for_target(
    mode: str,
    depot_id: int | None,
    depot_version: int | None,
    depot_crc: int | None,
) -> BuildProfile:
    target = build_target(mode, depot_id, depot_version, depot_crc)
    if target in PATCH_COMPATIBILITY:
        return PATCH_COMPATIBILITY[target]
    if len(target) == 3:
        target = target[:2]
    return PATCH_COMPATIBILITY.get(target, PATCH_COMPATIBILITY["generic"])
