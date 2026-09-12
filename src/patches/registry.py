from patches.build_852_0.hl2_assets.patch import DEFINITION as HL2ASSETSPATCH
from patches.build_852_0.search_paths import DEFINITION as SEARCHPATHSPATCH
from patches.build_852_0.sound_manifest import DEFINITION as SOUNDMANIFESTPATCH
from patches.build_852_0.dialogue import DEFINITION as DIALOGUEFIXPATCH
from patches.build_852_0.subtitles.patch import DEFINITION as SUBTITLES8520PATCH
from patches.build_852_0.continuous_campaign.patch import DEFINITION as CONTINUOUSCAMPAIGNPATCH
from patches.build_852_0.vscript_scope_fix import DEFINITION as VSCRIPTSCOPEFIXPATCH
from patches.build_852_0.smooth_jazz import DEFINITION as SMOOTHJAZZPATCH
from patches.generic.thread_fix.patch import DEFINITION as THREADFIXPATCH
from patches.generic.launchers import DEFINITION as LAUNCHERSPATCH
from patches.build_852_0.hammer import DEFINITION as HAMMERPATCH
from patches.build_852_0.extra_assets.patch import DEFINITION as PRERELEASEASSETSPATCH
from patches.generic.multicore import DEFINITION as MULTICOREPATCH
from patches.generic.goldberg import DEFINITION as GOLDBERGPATCH
from patches.build_852_1.legacy_paint import DEFINITION as LEGACYPAINTPATCH
from patches.build_852_1.extra_assets.from_july_2010 import DEFINITION as JULY2010ASSETSPATCH
from patches.build_852_1.extra_assets.from_july_2009 import DEFINITION as JULY2009ASSETSPATCH
from patches.build_852_1.extra_assets.bundled import DEFINITION as MARCHASSETSPATCH
from patches.build_852_1.hammer import DEFINITION as HAMMER8521PATCH
from patches.build_841_0_prereset.missing_launcher.patch import DEFINITION as HL2LAUNCHERPATCH
from patches.build_841_0_prereset.tier0_thread_limit import DEFINITION as TIER0THREADLIMIT8410PATCH
from patches.build_852_0.multiplayer.patch import DEFINITION as MULTIPLAYER8520PATCH
from patches.build_852_2.hammer import DEFINITION as HAMMER8522PATCH
from patches.build_852_0.node_graphs.patch import DEFINITION as NODEGRAPHS8520PATCH
from patches.build_841_0_prereset.node_graphs.patch import DEFINITION as NODEGRAPHS8410PATCH
from patches.build_841_0_prereset.progression_fixes.patch import DEFINITION as PROGRESSIONFIXES8410PATCH
from patches.generic.profile import PROFILE as GENERIC
from patches.build_852_0.profile import PROFILE as BUILD_852_0
from patches.build_852_1.profile import PROFILE as BUILD_852_1
from patches.build_841_0_prereset.profile import PROFILE as BUILD_841_0_PRERESET
from patches.build_852_2.profile import PROFILE as BUILD_852_2

DEFINITIONS = (
    HL2ASSETSPATCH,
    SEARCHPATHSPATCH,
    SOUNDMANIFESTPATCH,
    DIALOGUEFIXPATCH,
    SUBTITLES8520PATCH,
    CONTINUOUSCAMPAIGNPATCH,
    VSCRIPTSCOPEFIXPATCH,
    SMOOTHJAZZPATCH,
    THREADFIXPATCH,
    LAUNCHERSPATCH,
    HAMMERPATCH,
    PRERELEASEASSETSPATCH,
    MULTICOREPATCH,
    GOLDBERGPATCH,
    LEGACYPAINTPATCH,
    JULY2010ASSETSPATCH,
    JULY2009ASSETSPATCH,
    MARCHASSETSPATCH,
    HAMMER8521PATCH,
    HL2LAUNCHERPATCH,
    TIER0THREADLIMIT8410PATCH,
    MULTIPLAYER8520PATCH,
    HAMMER8522PATCH,
    NODEGRAPHS8520PATCH,
    NODEGRAPHS8410PATCH,
    PROGRESSIONFIXES8410PATCH,
)

PROFILES = (GENERIC, BUILD_852_0, BUILD_852_1, BUILD_841_0_PRERESET, BUILD_852_2,)

from patches.selection import validate_registry, ordered_definitions

validate_registry(DEFINITIONS, PROFILES)
DEFINITIONS = ordered_definitions(DEFINITIONS)
BY_ID = {item.id: item for item in DEFINITIONS}
PATCHES = tuple(item.implementation for item in DEFINITIONS)
PATCH_DEPENDENCIES = {item.id: item.dependencies for item in DEFINITIONS if item.dependencies}
PATCH_COMPATIBILITY = {profile.target if profile.target is not None else "generic": profile for profile in PROFILES}
