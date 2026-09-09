from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='852_1', target=(852, 1),
    optional=frozenset(['852_1.extra_assets.bundled', '852_1.extra_assets.from_july_2009', '852_1.extra_assets.from_july_2010', '852_1.hammer', '852_1.legacy_paint', 'goldberg', 'thread_fix']),
    required=frozenset(['launchers']),
    first_run_audio=True,
)
