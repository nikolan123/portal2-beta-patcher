"""
Copy assets from Half-Life 2
This patch extracts the supplied hl2 install's assets from vpk files and copies them over to portal.
"""
from __future__ import annotations

from patches.definitions import PatchDefinition, Resource
from patches.helpers.retail_assets import CuratedHl2AssetsPatch, load_asset_allowlist


ASSET_RESOURCE = Resource("build_852_0/hl2_assets", "assets.txt")
HL2_ASSET_ALLOWLIST = load_asset_allowlist(ASSET_RESOURCE)


class Hl2AssetsPatch(CuratedHl2AssetsPatch):
    id = "852_0.hl2_assets"
    display_name = "Half-Life 2 assets"
    description = "Copy materials, models, sounds, and scripts this beta needs from your Half-Life 2 install."
    allowlist = HL2_ASSET_ALLOWLIST
    asset_marker = "hl2-assets-curated-v2\n"
    require_all_assets = False  # Silently skip allowlisted files absent from the source.


DEFINITION = PatchDefinition(
    Hl2AssetsPatch(),
    requirements=frozenset({"hl2"}),
    resources=(ASSET_RESOURCE,),
    progress_range=(0.58, 0.88),
)
