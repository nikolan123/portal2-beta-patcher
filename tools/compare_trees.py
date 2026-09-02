from __future__ import annotations

import hashlib
from pathlib import Path
import sys


def files(root: Path) -> dict[str, Path]:
    return {path.relative_to(root).as_posix().casefold(): path for path in root.rglob("*") if path.is_file()}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_trees.py FIRST SECOND")
        return 2
    first_root, second_root = map(lambda value: Path(value).resolve(), sys.argv[1:])
    first, second = files(first_root), files(second_root)
    missing = sorted(first.keys() - second.keys())
    extra = sorted(second.keys() - first.keys())
    different: list[str] = []
    for relative in sorted(first.keys() & second.keys()):
        one, two = first[relative], second[relative]
        if one.stat().st_size != two.stat().st_size or digest(one) != digest(two):
            different.append(relative)
    print(f"first files: {len(first)}")
    print(f"second files: {len(second)}")
    print(f"missing: {len(missing)}")
    print(f"extra: {len(extra)}")
    print(f"different: {len(different)}")
    for label, values in (("missing", missing), ("extra", extra), ("different", different)):
        for value in values[:20]:
            print(f"{label}: {value}")
    return 1 if missing or extra or different else 0


if __name__ == "__main__":
    raise SystemExit(main())
