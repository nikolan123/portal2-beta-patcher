from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='generic', target=None,
    optional=frozenset(['disable_survey', 'goldberg', 'multicore', 'thread_fix', 'full_hl2_assets', 'full_tf_assets']),
    required=frozenset(['launchers']),
)
