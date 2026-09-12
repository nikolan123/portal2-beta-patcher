from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='841_0_prereset', target=(841, 0, 2211371384),
    optional=frozenset(['841_0_prereset.missing_launcher', '841_0_prereset.hl2_assets', '841_0_prereset.node_graphs', '841_0_prereset.progression_fixes', '841_0_prereset.tier0_thread_limit', 'goldberg', 'multicore', 'thread_fix']),
    required=frozenset(['launchers']),
)
