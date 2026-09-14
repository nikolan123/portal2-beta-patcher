from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='generic', target=None,
    optional=frozenset(['disable_survey', 'goldberg', 'multicore', 'thread_fix']),
    required=frozenset(['launchers']),
)
