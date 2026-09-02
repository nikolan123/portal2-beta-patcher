# Patches

List of patches applied

## p1 - Half-Life 2 assets

The beta expects the shared Half-Life 2 files that Steam used to mount for it, but those files are not part of the `852_0` depot itself. Modern Steam keeps them inside VPK archives that this extracts and takes the needed stuff from. Voice vpk is excluded since it was causing problems and I don't think is needed.

TODO: copy only the needed assets

## p2 - Search paths

This patch edits `portal2/GameInfo.txt` and adds the missing `platform` and `hl2` search paths. It also saves the original as `GameInfo.original.bak` before making a change.

## p3 - Sound manifest

Source does not discover every sound script automatically. The files must be listed in `portal2/scripts/game_sounds_manifest.txt` before the engine will load their sound definitions.

This patch adds the missing HL2 sound-script entries to that manifest. And of course backs up the original first.

## p4 - GLaDOS dialogue

Some maps expect an actor named `@glados` to exist when dialogue is played. In this build it is missing, which stops those lines from working correctly.

This patch creates `portal2/scripts/vscripts/mapspawn.nut`. One second after the map starts, the script checks for `@glados`, if none exists, it creates a hidden `generic_actor` with that name far outside the playable map. The delay matters because creating the actor immediately can crash this build.

If a different `mapspawn.nut` already exists, it is preserved as `mapspawn.original.bak` before the replacement is written, though that is redunant so it might be removed.

## p5 - Source Thread Fix

Old Source builds can fail on modern systems that expose more processor threads than the engine expects.

This patch downloads [Mike's Source Thread Fix](https://mikes.software/threadfix/) directly from his site. The hash is checked to make sure the files are as expected.

## p6 - Launcher

This patch creates a launcher for portal as `Launch Portal 2.cmd` so the game can be launched without using a command line.
