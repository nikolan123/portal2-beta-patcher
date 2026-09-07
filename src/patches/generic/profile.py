from patches.definitions import BuildProfile, ChoiceGroup

PROFILE = BuildProfile(
    id='generic', target=None,
    optional=frozenset(['goldberg', 'multicore', 'thread_fix']),
    required=frozenset(['launchers']),
)
