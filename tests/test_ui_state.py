from pathlib import Path

from extractor import CatalogTarget
from models import RevisionInput
from ui import GITHUB_ISSUES_URL, back_screen_for_mode, default_generic_output, is_core_hub_target, patch_ids_for_mode


def target(ready=True):
    chain = (
        RevisionInput(852, 0, 0x10, Path("0.blob"), Path("0.dat")),
        RevisionInput(852, 1, 0x11, Path("1.blob"), Path("1.dat")),
        RevisionInput(852, 2, 0x12, Path("2.blob"), Path("2.dat")),
    )
    return CatalogTarget(
        852, 2, 0x12, Path("2.blob"), ready,
        "Ready" if ready else "Missing DAT", chain,
        estimated_size=1_610_612_736,
    )


def test_mode_specific_patch_lists():
    assert patch_ids_for_mode("generic", 852, 1) == ("p5", "p10", "p11", "p12", "p13", "p14", "p15")
    assert patch_ids_for_mode("generic", 852, 2) == ("p5", "p9", "p10")
    assert patch_ids_for_mode("generic", 841, 1) == ("p5", "p9", "p10")
    assert patch_ids_for_mode("generic", 841, 0, 0x83CED978) == ("p5", "p9", "p10", "p16", "p17")
    assert "p4" in patch_ids_for_mode("852_0")
    assert "p9" not in patch_ids_for_mode("852_0")
    assert patch_ids_for_mode("852_0")[-1] == "p10"


def test_support_link_uses_the_project_issue_tracker():
    assert GITHUB_ISSUES_URL == "https://github.com/nikolan123/portal2-beta-patcher/issues"


def test_default_output(tmp_path):
    selected = target()
    assert default_generic_output(tmp_path / "archives", selected) == tmp_path / "852_2_fixed"


def test_852_0_catalog_target_uses_core_hub_workflow():
    selected = target()
    assert not is_core_hub_target(selected)
    assert is_core_hub_target(
        CatalogTarget(852, 0, 0x90B0FE8E, Path("852_0.blob"), True, "Ready")
    )
    assert not is_core_hub_target(
        CatalogTarget(841, 0, 0x83CED978, Path("841_0.blob"), True, "Ready")
    )


def test_back_navigation_is_mode_specific():
    assert back_screen_for_mode("generic") == "generic_files"
    assert back_screen_for_mode("852_0") == "852_files"


def test_incomplete_targets_are_not_selectable():
    assert target().ready
    assert not target(False).ready


def test_ready_target_label_shows_approximate_final_size():
    assert target().label.endswith("[00000012] - ~1.5 GB")
    assert "Ready" not in target().label
    assert "~" not in target(False).label
    assert target(False).label.endswith("Missing DAT")
