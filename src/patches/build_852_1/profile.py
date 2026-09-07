from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='852_1', target=(852, 1),
    optional=frozenset(['852_1.extra_assets.bundled', '852_1.extra_assets.from_july_2009', '852_1.extra_assets.from_july_2010', '852_1.legacy_paint', '852_1.tier0_thread_limit', 'goldberg', 'thread_fix']),
    required=frozenset(['launchers']),
)
