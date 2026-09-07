"""Public patch catalog and selection API."""
from patches.registry import PATCHES, DEFINITIONS, BY_ID, PROFILES, PATCH_COMPATIBILITY, PATCH_DEPENDENCIES
from patches.compatibility import build_target, patch_set_for_target
from patches.selection import compatible_patch_ids, selectable_patch_ids, normalize_patch_ids, resolve_selection
