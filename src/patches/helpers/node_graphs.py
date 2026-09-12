"""Install generated node graphs when the BSP revision integer matches."""
from dataclasses import dataclass
from pathlib import Path
import struct
from zipfile import ZipFile

from models import BuildCancelled, PatchContext, ProgressCallback, ProgressEvent
from patches.base import PatchError, atomic_write, backup_file
from patches.definitions import Resource
from patches.resources import resource_path


@dataclass(frozen=True)
class NodeGraphsPatch:
    id: str
    resource: Resource
    display_name: str = "Prebuilt node graphs"
    description: str = "Install prebuilt node graphs to avoid the rebuilding message."

    def _entries(self, context: PatchContext):
        root = context.root / "game" if (context.root / "game" / "portal2").is_dir() else context.root
        maps = root / "portal2" / "maps"
        with ZipFile(resource_path(self.resource)) as archive:
            for name in archive.namelist():
                if Path(name).name != name or "/" in name or "\\" in name or not name.endswith(".ain"):
                    raise PatchError("Unexpected file in node graph archive")
                bsp = maps / (name[:-4] + ".bsp")
                if not bsp.is_file():
                    continue
                data = archive.read(name)
                with bsp.open("rb") as stream:
                    header = stream.read(1036)
                if len(data) < 16 or len(header) < 1036 or header[:4] != b"VBSP":
                    raise PatchError(f"Invalid map or node graph: {name}")
                if struct.unpack_from("<i", data, 4)[0] != struct.unpack_from("<i", header, 1032)[0]:
                    continue  # Leave maps with a different revision to the engine.
                yield maps / "graphs" / name, data

    def check(self, context: PatchContext) -> bool:
        return any(not path.is_file() or path.read_bytes() != data
                   for path, data in self._entries(context))

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        entries = list(self._entries(context))
        for index, (path, data) in enumerate(entries, 1):
            if context.cancel_event.is_set():
                raise BuildCancelled()
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file() or path.read_bytes() != data:
                if path.exists():
                    backup_file(path, path.name + ".original.bak", context)
                atomic_write(path, data)
            progress(ProgressEvent(self.id, index, len(entries), f"Installing {path.name}"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise PatchError("Node graph installation failed verification")
