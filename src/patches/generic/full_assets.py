"""Optional full retail content copies, without asset lists."""
from pathlib import Path
import re
import shutil

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file
from patches.definitions import PatchDefinition
from vpk import DIR_ARCHIVE_INDEX, VPKArchive, safe_relative_path


SEARCH_PATHS = re.compile(rb'((?:"SearchPaths"|SearchPaths)\s*\{)(.*?)(\r?\n[ \t]*\})', re.I | re.S)


def mount_content(data: bytes, folder: str) -> bytes:
    match = SEARCH_PATHS.search(data)
    if match is None:
        raise PatchError("GameInfo.txt has no SearchPaths block")
    values = re.findall(rb'(?im)^[ \t]*"?Game"?[ \t]+(?:"([^"\r\n]+)"|([^ \t\r\n]+))', match[2])
    for quoted, bare in values:
        value = (quoted or bare).decode('utf-8').replace('\\', '/').casefold()
        if value in {folder, '|gameinfo_path|../' + folder}:
            return data
    newline = b'\r\n' if b'\r\n' in data else b'\n'
    line = b'\t\t\tGame\t\t\t\t"|gameinfo_path|..\\' + folder.encode('ascii') + b'"'
    return data[:match.end(2)] + newline + line + data[match.end(2):]


def content_plan(source: Path):
    files = sorted(path for path in source.rglob('*') if path.is_file())
    vpks = [path for path in files if path.suffix.casefold() == '.vpk']
    archives = []
    consumed = set()
    # Read directory indexes first so their data segments are not mistaken for
    # standalone archives. Standalone VPKs use embedded data instead.
    for path in sorted(vpks, key=lambda p: (not p.name.casefold().endswith('_dir.vpk'), p)):
        if path in consumed:
            continue
        archive = VPKArchive(path)
        consumed.add(path)
        for index in {entry.archive_index for entry in archive.entries} - {DIR_ARCHIVE_INDEX}:
            segment = archive._segment_path(index)
            if not segment.is_file():
                raise PatchError(f"Missing VPK segment: {segment}")
            consumed.add(segment)
        archives.append(archive)
    plan = [(path.relative_to(source).as_posix(), path, None)
            for path in files if path not in consumed]
    seen = {relative.casefold() for relative, _, _ in plan}
    for archive in archives:
        prefix = archive.directory_file.parent.relative_to(source)
        for entry in archive.entries:
            relative = (prefix / Path(*safe_relative_path(entry.path).parts)).as_posix()
            if relative.casefold() not in seen:
                plan.append((relative, archive, entry))
                seen.add(relative.casefold())
    return plan


class FullRetailAssetsPatch:
    def __init__(self, folder: str, label: str, source_attribute: str, additional_folders: tuple[str, ...] = ()):
        self.folder = folder
        self.folders = (folder, *additional_folders)
        self.label = label
        self.source_attribute = source_attribute
        self.id = f'full_{folder}_assets'
        self.display_name = f'All {label} assets'
        self.description = f"Copy installed {', '.join(self.folders)} content, unpacking all VPKs. Uses several GB."

    def _paths(self, context: PatchContext):
        source = getattr(context, self.source_attribute)
        if source is None:
            raise PatchError(f'A {self.label} installation is required')
        runtime = context.root / 'game' if (context.root / 'game/portal2/GameInfo.txt').is_file() else context.root
        folders = [self.folder]
        folders.extend(folder for folder in self.folders[1:] if (source / folder).is_dir())
        for folder in folders:
            content_source = (source / folder).resolve()
            destination = (runtime / folder).resolve()
            if (content_source.is_relative_to(runtime.resolve())
                    or destination.is_relative_to(content_source)):
                raise PatchError('Retail source and build output must be separate folders')
        return source, runtime, runtime / 'portal2/GameInfo.txt', folders

    def check(self, context: PatchContext) -> bool:
        # Reapplying scans the full source again and fills missing files.
        # There is no completion marker or fixed list to become outdated.
        return True

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        source, runtime, gameinfo, folders = self._paths(context)
        original = gameinfo.read_bytes()
        mounted = original
        progress(ProgressEvent(self.id, 0, 1, f'Reading all {self.label} assets'))
        plan = []
        for folder in folders:
            mounted = mount_content(mounted, folder)
            for relative, origin, entry in content_plan(source / folder):
                plan.append((f'{folder}/{relative}', origin, entry))
        for index, (relative, origin, entry) in enumerate(plan, 1):
            if context.cancel_event.is_set():
                raise BuildCancelled('Build cancelled')
            target = runtime.joinpath(*safe_relative_path(relative).parts)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if entry is None:
                    temporary = target.with_name(target.name + '.patcher.tmp')
                    shutil.copy2(origin, temporary)
                    temporary.replace(target)
                else:
                    # one of the tf2 vpks had stale CRC metadata
                    atomic_write(target, origin.read_entry(entry, verify_crc=False))
            elif not target.is_file():
                raise PatchError(f'Cannot copy retail file over a directory: {target}')
            if index == 1 or index == len(plan) or index % 100 == 0:
                progress(ProgressEvent(self.id, index, len(plan), f'{self.label}: {relative}'))
        if original != mounted:
            backup_name = f'GameInfo.before-full-{self.folder}.bak'
            if not gameinfo.with_name(backup_name).is_file():
                backup_file(gameinfo, backup_name, context)
            atomic_write(gameinfo, mounted)

    def verify(self, context: PatchContext) -> None:
        source, runtime, gameinfo, folders = self._paths(context)
        data = gameinfo.read_bytes()
        for folder in folders:
            if mount_content(data, folder) != data:
                raise PatchError(f'{self.label} content is not mounted: {folder}')
            for relative, _, _ in content_plan(source / folder):
                if context.cancel_event.is_set():
                    raise BuildCancelled('Build cancelled')
                if not (runtime / folder / relative).is_file():
                    raise PatchError(f'{self.label} asset was not copied: {folder}/{relative}')


ORDER_AFTER = frozenset({'852_0.hammer', '852_0.search_paths', '841_0_prereset.hl2_assets',
                         '852_1.hammer', '852_2.hammer'})
HL2_DEFINITION = PatchDefinition(FullRetailAssetsPatch('hl2', 'Half-Life 2', 'hl2_source', ('episodic', 'ep2')),
                                 default_selected=False, requirements=frozenset({'hl2'}), after=ORDER_AFTER)
TF2_DEFINITION = PatchDefinition(FullRetailAssetsPatch('tf', 'Team Fortress 2', 'tf2_source'),
                                 default_selected=False, requirements=frozenset({'tf2'}), after=ORDER_AFTER)
