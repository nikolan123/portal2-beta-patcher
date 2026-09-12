"""
Copy assets from Half-Life 2
This patch extracts the supplied hl2 install's assets from vpk files and copies them over to portal.
"""
from pathlib import Path

from patches.helpers.retail_assets import CuratedHl2AssetsPatch, load_asset_allowlist
from patches.definitions import PatchDefinition, Resource


ASSET_RESOURCE = Resource("build_841_0_prereset/hl2_assets", "assets.txt")
HL2_ASSET_ALLOWLIST = load_asset_allowlist(ASSET_RESOURCE)


class Hl2Assets8410Patch(CuratedHl2AssetsPatch):
    id = "841_0_prereset.hl2_assets"
    display_name = "Half-Life 2 assets"
    description = "Copy 25 missing materials and sounds from your Half-Life 2 install."
    allowlist = HL2_ASSET_ALLOWLIST
    asset_marker = "841_0-hl2-assets-complete\n"

    def _asset_folder(self, context):
        return context.root / "portal2_tempcontent"

    def _source_archives(self, source: Path):
        paths = list(super()._source_archives(source))
        episode_two = source / "ep2" / "ep2_pak_dir.vpk"
        if episode_two.is_file():
            paths.append(episode_two)
        return paths


DEFINITION = PatchDefinition(
    Hl2Assets8410Patch(),
    requirements=frozenset({"hl2"}),
    resources=(ASSET_RESOURCE,),
)
