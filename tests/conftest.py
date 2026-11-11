import struct
import zlib

import pytest


@pytest.fixture
def write_vpk():
    """Write a small real VPK, optionally with an external data segment."""
    from vpk import DIR_ARCHIVE_INDEX, VPK_SIGNATURE

    def write(path, files, split=False):
        groups = {}
        for relative, payload in files.items():
            folder, filename = relative.rsplit('/', 1)
            name, extension = filename.rsplit('.', 1)
            groups.setdefault(extension, {}).setdefault(folder, {})[name] = payload
        tree, body = bytearray(), bytearray()
        for extension, folders in groups.items():
            tree += extension.encode() + b'\0'
            for folder, names in folders.items():
                tree += folder.encode() + b'\0'
                for name, payload in names.items():
                    tree += name.encode() + b'\0'
                    tree += struct.pack('<IHHIIH', zlib.crc32(payload), 0,
                                        0 if split else DIR_ARCHIVE_INDEX, len(body), len(payload), 0xffff)
                    body += payload
                tree += b'\0'
            tree += b'\0'
        tree += b'\0'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack('<III', VPK_SIGNATURE, 1, len(tree)) + tree + (b'' if split else body))
        if split:
            path.with_name(path.name[:-8] + '_000.vpk').write_bytes(body)

    return write


@pytest.fixture
def retail_tool_vpk(write_vpk):
    """Create a small retail tool archive for Hammer integration tests."""
    def write(retail):
        files = {
            'materials/tools/toolsblocklight.vmt': b'LightmappedGeneric { $basetexture tools/toolsblocklight }',
            'materials/tools/toolsblocklight.vtf': b'blocklight texture',
            'materials/tools/toolsclip.vmt': b'retail clip material',
            'materials/tools/toolsclip.vtf': b'retail clip texture',
            'materials/dev/unrelated.vmt': b'do not copy',
        }
        write_vpk(retail / 'portal2/pak01_dir.vpk', files)
        return files

    return write
