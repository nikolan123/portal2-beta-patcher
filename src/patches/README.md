# Patches

## Structure and compatibility

Patches for one specific build are in `build_852_0`, `build_852_1`, and `build_841_0_prereset`. General patches are in `generic`. Patches for several specific builds are in `shared`. Each build's `profile.py` sets optional and required IDs for that build. The generic profile is the fallback for unknown builds.

<!-- compatibility:start -->

| Patch ID | 841_0_prereset | 852_0 | 852_1 | 852_2 | generic |
| --- | --- | --- | --- | --- | --- |
| `852_0.hl2_assets` | — | Optional | — | — | — |
| `852_0.search_paths` | — | Required | — | — | — |
| `852_0.sound_manifest` | — | Optional | — | — | — |
| `852_0.dialogue` | — | Optional | — | — | — |
| `852_0.subtitles` | — | Optional | — | — | — |
| `852_0.continuous_campaign` | — | Optional | — | — | — |
| `852_0.vscript_scope_fix` | — | Optional | — | — | — |
| `852_0.smooth_jazz` | — | Optional | — | — | — |
| `thread_fix` | Optional | Optional | Optional | Optional | Optional |
| `launchers` | Required | Required | Required | Required | Required |
| `852_0.hammer` | — | Optional | — | — | — |
| `852_0.extra_assets` | — | Optional | — | — | — |
| `multicore` | Optional | — | — | Optional | Optional |
| `goldberg` | Optional | Optional | Optional | Optional | Optional |
| `852_1.legacy_paint` | — | — | Optional | — | — |
| `852_1.extra_assets.from_july_2010` | — | — | Optional | — | — |
| `852_1.extra_assets.from_july_2009` | — | — | Optional | — | — |
| `852_1.extra_assets.bundled` | — | — | Optional | — | — |
| `852_1.hammer` | — | — | Optional | — | — |
| `841_0_prereset.missing_launcher` | Optional | — | — | — | — |
| `841_0_prereset.tier0_thread_limit` | Optional | — | — | — | — |
| `852_0.multiplayer` | — | Optional | — | — | — |
| `852_2.hammer` | — | — | — | Optional | — |

<!-- compatibility:end -->

## 852_0

These patches are specific to the July 2009 `852_0` build.

### 852_0.hl2_assets - Half-Life 2 assets

The beta expects the shared Half-Life 2 files that Steam used to mount for it, but those files are not part of the `852_0` depot itself. Modern Steam keeps them inside VPK archives that this extracts and takes the needed stuff from.

### 852_0.search_paths - Search paths

This patch adds the missing `portal2_tempcontent` and `platform` search paths. When Half-Life 2 content support is selected, it mounts `hl2` too. It saves the original as `GameInfo.original.bak` before making a change.

### 852_0.sound_manifest - Sound manifest

Source does not discover every sound script automatically. The files must be listed in `portal2/scripts/game_sounds_manifest.txt` before the engine will load their sound definitions.

This patch adds the missing HL2 sound-script entries to that manifest. And of course backs up the original first.

### 852_0.dialogue - GLaDOS dialogue

Some maps expect an actor named `@glados` to exist when dialogue is played. In this build it is missing, which stops those lines from working correctly.

This patch adds its setup to `portal2/scripts/vscripts/mapspawn.nut`. One second after the map starts, the script checks for `@glados`; if none exists, it creates a hidden `generic_actor` with that name far outside the playable map. The delay matters because creating the actor immediately can crash this build.

It also updates `portal2/scripts/vscripts/choreo/glados.nut`. Starting a new single-player dialogue block cancels every previously playing or queued GLaDOS scene, preventing lines from overlapping.

If a different `mapspawn.nut` already exists, it is preserved as `mapspawn.original.bak` before replacement.

### 852_0.subtitles - English subtitles

Installs the English subtitles in both raw and compiled Source formats. It includes the original Portal captions for reused dialogue and the captions transcribed for this build, styled to match retail Portal 2.

The Aquarium Core uses random sound groups that cannot select the caption for the WAV that actually played. A map script replaces those groups with individually named sounds. A smaller map script redirects three raw Curiosity Core WAVs through their existing Portal sound events so their captions display consistently.

This patch depends on `852_0.dialogue`, so dialogue runs first and subtitles then append their setup to `mapspawn.nut`.

### 852_0.continuous_campaign - Experimental speedrunning fixes

This patch is intended to make speedrunning tools work easier with this build. It installs entity LMPs that replace the campaign's hub `map` commands with `changelevel`, adds an end-of-run marker to hub 6, and fixes the slowtime upgrade when the earlier gun is skipped.

### 852_0.vscript_scope_fix - Mixup turret crash fix

This patches `portal2/bin/Server.dll` to check whether VScript successfully created an entity scope before using it. It also patches `portal2/bin/Client.dll` to clamp negative animation frames before selecting animation data. These missing checks can crash `p2_lab_mixup` while its turret group is being destroyed.

### 852_0.smooth_jazz - Remove copyrighted Smooth Jazz

This patch keeps the announcer dialogue in `PreHub42.wav` and `PreHub44.wav` but removes the copyrighted Smooth Jazz.

### 852_0.hammer - Hammer and HLMV tools

The Hammer and Half-Life Model Viewer programs are present in `852_0`, but the extracted depot is missing the layout and editor materials they expect.

This patch copies the `platform/materials/Editor` folder from the user's retail Portal 2 installation, moves the runtime into a normal `game` folder, writes the Portal 2 Hammer configuration, and creates separate launchers for Hammer and HLMV. The files are physically moved, no junctions anymore!

It also patches this build's `game/bin/tier0.dll` thread table from 32 slots to 128. The original DLL is preserved as `tier0.original.bak`, and the patch is accepted only when both the original and resulting SHA-256 hashes match the known files.

Hammer's configuration contains the installation path. If the completed build is moved later, the patcher's **Fix moved build** action rewrites it without extracting or copying the build again.

### 852_0.extra_assets - Additional prerelease assets

This build of Portal uses a few files that are neither included in the beta nor available in Half-Life 2.

This patch installs only those five runtime assets and adds `particles/achievement.pcf` to the existing particle manifest. The assets are stored together in a small ZIP.

### 852_0.multiplayer - Multiplayer fixes

This installs a source-built ASI for the `852_0` engine and server. At runtime it guards a broken connection path, makes engine initialization open the network sockets, and gets player names from the engine instead of the empty server-side field.

The game DLLs remain stock. The ASI loader comes from pinned official DxWrapper v1.8.8600.25 that is downloaded and SHA-256 verified while building the patcher, these loader binaries are not stored in this repository. License stored in `.p2patcher/LICENCE-dxwrapper.txt`.

## 841_0 Pre-reset

`83ced978` manifest

### 841_0_prereset.missing_launcher - Missing hl2.exe fix

This installs a small prebuilt executable produced from `src/patches/build_841_0_prereset/missing_launcher/native/hl2.cpp` as `hl2.exe`.

### 841_0_prereset.tier0_thread_limit - Tier0 Thread Limit

This build's `tier0.dll` has a table with only 32 thread id slots, which can fail on modern CPUs that expose more threads.

This patch expands that table to 128 slots.

## 852_1

These patches are specific to depot 852 version 1.

### 852_1.legacy_paint - Legacy Paint Maps

Some older paint maps do not contain the `paintinmap` setting expected by this version of the engine, so their speed and bounce paint does not work.

This patch changes the default in `bin/engine.dll` from disabled to enabled. Maps that explicitly contain the setting still use their own value. The original DLL is preserved as `engine.original.bak`.

### 852_1.extra_assets.from_july_2010 - July 2010 Assets

Copies tempcontent from July 2010 852_2.

### 852_1.extra_assets.from_july_2009 - July 2009 Assets

Copies tempcontent from July 2009 852_0. When both this patch and 852_1.extra_assets.from_july_2010 are selected, the folders are merged, with the 852_0 files taking priority.

### 852_1.extra_assets.bundled - March build assets

Installs some missing materials and models in the supplied March build patch. The assets are bundled in a ZIP.

### 852_1.hammer - Hammer

This patch configures Portal 2 Hammer, creates the mapsource folder, mounts the included editor materials, expands this build's `tier0.dll` thread-ID table from 32 to 128 slots, and creates a movable launcher.

Hammer's configuration contains the installation path. If the completed build is moved later, the patcher's **Fix moved build** action rewrites it for its new folder.

## 852_2

### 852_2.hammer - Hammer

This patch configures Portal 2 Hammer, creates the mapsource folder, mounts the included editor materials, applies the build-specific tier0 thread fix, and creates a movable launcher.

Hammer's configuration contains the installation path. If the completed build is moved later, the patcher's **Fix moved build** action rewrites it for its new folder.

## Generic

This is the patch list for builds that do not have their own entry yet.

### thread_fix - Source Thread Fix

Old Source builds can fail on modern systems that expose more processor threads than the engine expects.

This patch installs the bundled [Source Thread Fix](https://mikes.software/threadfix/) wrapper and keeps its required license in the patcher folder.

### launchers - Launcher

This patch creates a launcher for portal as `Launch Portal 2.cmd` so the game can be launched without using a command line.

### multicore - Disable multicore rendering

Some Portal 2 prerelease builds render reflections incorrectly when queued material rendering is active.

This patch creates `portal2/cfg/patcher_multicore.cfg` containing `mat_queue_mode 0`. The generated launcher runs that separate file when it exists.

### goldberg - Goldberg emulator

This patch uses a Goldberg ZIP selected by the user. The ZIP must match the pinned SHA-256 before anything is installed.

It backs up every original 32-bit `steam_api.dll` as `steam_api.original.bak`, generates `steam_interfaces.txt` from the original library, and installs the replacement from the verified ZIP.

## Adding patches and builds

- Put build-specific patches in `build_x/`, general patches in `generic/`, and patches for several specific builds in `shared/`.
- Follow an existing patch: implement `check`, `apply`, and `verify`, then export a `DEFINITION` with a descriptive ID. Keep assets and native sources beside the patch.
- Import the definition in `registry.py`, add it to `DEFINITIONS`, and list its ID in each supported build profile. Use `dependencies` for required patches and `after` for execution order.
- To add a build, create its `profile.py` with the depot/version (and CRC if needed), list its patches, and register it in `PROFILES`.

Run `uv run pytest -q` after changes. If build support changes, run `uv run python tools/patch-docs.py` to update the compatibility table.
