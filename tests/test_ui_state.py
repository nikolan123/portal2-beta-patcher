from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from dataclasses import replace
import tkinter as tk

from patches import DEFINITIONS
from ui import PatcherUI

from extractor import CatalogTarget
from models import RevisionInput
from ui import GITHUB_ISSUES_URL, back_screen_for_mode, default_generic_output, is_core_hub_target, patch_ids_for_mode


def test_live_folder_updates_survive_chooser_navigation(monkeypatch):
    monkeypatch.setattr(PatcherUI, 'detect_hl2', lambda self: None)
    monkeypatch.setattr(PatcherUI, 'detect_portal2', lambda self: None)
    app = PatcherUI()
    app.withdraw()
    errors = []
    app.report_callback_exception = lambda *args: errors.append(args)
    try:
        app.selected_target = replace(target(), depot_id=841, version=0, crc=0x83CED978)
        app.show_generic_patch_chooser()
        expected = patch_ids_for_mode('generic', 841, 0, 0x83CED978)
        assert len(app.generic_patch_controls) == len(expected)

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        for _ in range(2):
            entry = next(w for w in descendants(app.container)
                         if isinstance(w, tk.Entry) and str(w.cget('textvariable')) == str(app.hl2_var))
            group, checkbox, description, *_ = app.generic_patch_controls[0]
            entry.delete(0, tk.END)
            entry.insert(0, r'D:\SteamLibrary\steamapps\common\Half-Life 2')
            assert str(checkbox.cget('state')) == 'normal'
            checkbox.invoke()
            assert app.patch_vars[group.patch_ids[0]].get()
            entry.delete(0, tk.END)
            assert str(checkbox.cget('state')) == 'disabled'
            assert not app.patch_vars[group.patch_ids[0]].get()
            assert 'Unavailable' in description.cget('text')
            app.show_mode_selection()
            assert not app.generic_patch_controls
            app.hl2_var.set('')
            app.show_files()
            app.show_generic_patch_chooser()
            app.portal2_var.set('')
            assert len(app.generic_patch_controls) == len(expected)
        assert errors == []
    finally:
        app.destroy()


def test_dependency_checkbox_cannot_be_cleared_while_subtitles_selected():
    variables = {}
    for item in DEFINITIONS:
        state = [False]
        variables[item.id] = Mock(
            get=lambda state=state: state[0],
            set=lambda value, state=state: state.__setitem__(0, value),
        )
    ui = SimpleNamespace(patch_vars=variables, current_mode='852_0')
    PatcherUI.set_patch_choice(ui, ('852_0.subtitles',), True)
    assert variables['852_0.dialogue'].get()
    PatcherUI.set_patch_choice(ui, ('852_0.dialogue',), False)
    assert variables['852_0.dialogue'].get()
    ids = PatcherUI.selected_patch_ids(ui)
    assert ids.index('852_0.dialogue') < ids.index('852_0.subtitles')
    PatcherUI.set_patch_choice(ui, ('852_0.subtitles',), False)
    PatcherUI.set_patch_choice(ui, ('852_0.dialogue',), False)
    assert not variables['852_0.dialogue'].get()


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
    assert patch_ids_for_mode("generic", 852, 1) == ("thread_fix", "goldberg", "852_1.legacy_paint", "852_1.extra_assets.from_july_2010", "852_1.extra_assets.from_july_2009", "852_1.extra_assets.bundled", "852_1.hammer")
    assert patch_ids_for_mode("generic", 852, 2) == ("thread_fix", "multicore", "goldberg", "852_2.hammer")
    assert patch_ids_for_mode("generic", 841, 1) == ("thread_fix", "multicore", "goldberg")
    assert patch_ids_for_mode("generic", 841, 0, 0x83CED978) == ("841_0_prereset.hl2_assets", "thread_fix", "multicore", "goldberg", "841_0_prereset.missing_launcher", "841_0_prereset.tier0_thread_limit", "841_0_prereset.node_graphs", "841_0_prereset.progression_fixes")
    assert "852_0.dialogue" in patch_ids_for_mode("852_0")
    assert "852_0.subtitles" in patch_ids_for_mode("852_0")
    assert "852_0.continuous_campaign" in patch_ids_for_mode("852_0")
    assert "multicore" not in patch_ids_for_mode("852_0")
    assert "852_0.multiplayer" in patch_ids_for_mode("852_0")
    assert "852_0.node_graphs" in patch_ids_for_mode("852_0")


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
