from patches.definitions import BuildProfile


PROFILE = BuildProfile(
    id="852_2",
    target=(852, 2),
    optional=frozenset({"thread_fix", "multicore", "goldberg", "852_2.hammer"}),
    required=frozenset({"launchers"}),
)
