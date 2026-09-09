from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='852_0', target=(852, 0),
    optional=frozenset(['852_0.continuous_campaign', '852_0.dialogue', '852_0.extra_assets', '852_0.hammer', '852_0.hl2_assets', '852_0.multiplayer', '852_0.sound_manifest', '852_0.subtitles', '852_0.vscript_scope_fix', 'goldberg', 'thread_fix']),
    required=frozenset(
        ['852_0.search_paths', 'launchers']),
        first_run_audio=True,
        groups=(ChoiceGroup(("852_0.hl2_assets", "852_0.sound_manifest"), "Half-Life 2 content support", "Copy the required HL2 assets and register their sound scripts."),),
)
