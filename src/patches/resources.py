"""One resource inventory for source execution and PyInstaller."""
from pathlib import Path
from patches.definitions import Resource

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parent.parent


def resource_path(resource: Resource, *, package_root: Path = PACKAGE_ROOT,
                  repository_root: Path = REPOSITORY_ROOT) -> Path:
    packaged = package_root / resource.package / resource.name
    if packaged.is_file() or not resource.native:
        return packaged
    return repository_root / 'build' / 'native' / resource.package / resource.name


def packaging_data(definitions) -> list[tuple[str, str]]:
    result = []
    seen = set()
    for definition in definitions:
        for resource in definition.resources:
            if resource in seen:
                continue
            seen.add(resource)
            source = resource_path(resource)
            if not source.is_file() or not source.stat().st_size:
                raise FileNotFoundError(f'Missing required patch resource: {source}')
            result.append((str(source), 'patches/' + resource.package))
    return result
