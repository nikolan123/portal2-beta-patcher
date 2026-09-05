# Patches

## 852_0

These patches are specific to the July 2009 `852_0` build.

### p1 - Half-Life 2 assets

The beta expects the shared Half-Life 2 files that Steam used to mount for it, but those files are not part of the `852_0` depot itself. Modern Steam keeps them inside VPK archives that this extracts and takes the needed stuff from.

### p2 - Search paths

This patch adds the missing `portal2_tempcontent` and `platform` search paths. When Half-Life 2 content support is selected, it mounts `hl2` too. It saves the original as `GameInfo.original.bak` before making a change.

### p3 - Sound manifest

Source does not discover every sound script automatically. The files must be listed in `portal2/scripts/game_sounds_manifest.txt` before the engine will load their sound definitions.

This patch adds the missing HL2 sound-script entries to that manifest. And of course backs up the original first.

### p4 - GLaDOS dialogue

Some maps expect an actor named `@glados` to exist when dialogue is played. In this build it is missing, which stops those lines from working correctly.

This patch creates `portal2/scripts/vscripts/mapspawn.nut`. One second after the map starts, the script checks for `@glados`, if none exists, it creates a hidden `generic_actor` with that name far outside the playable map. The delay matters because creating the actor immediately can crash this build.

If a different `mapspawn.nut` already exists, it is preserved as `mapspawn.original.bak` before the replacement is written, though that is redunant so it might be removed.

### p7 - Hammer and HLMV tools

The Hammer and Half-Life Model Viewer programs are present in `852_0`, but the extracted depot is missing the layout and editor materials they expect.

This patch copies the `platform/materials/Editor` folder from the user's retail Portal 2 installation, creates the `game` and `content` folders, writes the Portal 2 Hammer configuration, and creates separate launchers for Hammer and HLMV.

It also patches this build's `bin/tier0.dll` thread table from 32 slots to 128. The original DLL is preserved as `tier0.original.bak`, and the patch is accepted only when both the original and resulting SHA-256 hashes match the known files.

Hammer's configuration and the `game` junctions contain the installation path. If the completed build is moved later, the patcher's **Fix moved build** action rewrites those paths without extracting or copying the build again.

### p8 - Additional prerelease assets

This build of Portal uses a few files that are neither included in the beta nor available in Half-Life 2.

This patch installs only those five runtime assets and adds `particles/achievement.pcf` to the existing particle manifest. The assets are stored together in a small ZIP.

## 852_1

These patches are specific to depot 852 version 1.

### p11 - Legacy Paint Maps

Some older paint maps do not contain the `paintinmap` setting expected by this version of the engine, so their speed and bounce paint does not work.

This patch changes the default in `bin/engine.dll` from disabled to enabled. Maps that explicitly contain the setting still use their own value. The original DLL is preserved as `engine.original.bak`.

### p12 - July 2010 Assets

Copies tempcontent from July 2010 852_2.

### p13 - July 2009 Assets

Copies tempcontent from July 2009 852_0. When both this patch and p12 are selected, the folders are merged, with the 852_0 files taking priority.

## Generic

This is the patch list for builds that do not have their own entry yet.

### p5 - Source Thread Fix

Old Source builds can fail on modern systems that expose more processor threads than the engine expects.

This patch downloads [Mike's Source Thread Fix](https://mikes.software/threadfix/) directly from his site. The hash is checked to make sure the files are as expected.

### p6 - Launcher

This patch creates a launcher for portal as `Launch Portal 2.cmd` so the game can be launched without using a command line.

### p9 - Disable multicore rendering

Some Portal 2 prerelease builds render reflections incorrectly when queued material rendering is active.

This patch creates `portal2/cfg/patcher_multicore.cfg` containing `mat_queue_mode 0`. The generated launcher runs that separate file when it exists.

### p10 - Goldberg emulator

This patch uses a Goldberg ZIP selected by the user. The ZIP must match the pinned SHA-256 before anything is installed.

It backs up every original 32-bit `steam_api.dll` as `steam_api.original.bak`, generates `steam_interfaces.txt` from the original library, and installs the replacement from the verified ZIP.
