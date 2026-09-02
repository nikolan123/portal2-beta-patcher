from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

from models import PatchContext


class PatchError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backup_file(path: Path, name: str, context: PatchContext) -> Path:
    backup = path.with_name(name)
    if backup.exists():
        if backup.read_bytes() != path.read_bytes():
            raise PatchError(f"Refusing to replace unexpected backup: {backup}")
    else:
        shutil.copy2(path, backup)
        context.report.backups.append(str(backup.relative_to(context.root)))
    return backup


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".patcher.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)

