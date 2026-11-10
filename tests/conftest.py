import struct
import zlib

import pytest


@pytest.fixture
def retail_tool_vpk():
    """Create a small retail tool archive for Hammer integration tests."""
    from vpk import DIR_ARCHIVE_INDEX, VPK_SIGNATURE

    def write(retail):
        files = {
            'materials/tools/toolsblocklight.vmt': b'LightmappedGeneric { $basetexture tools/toolsblocklight }',
            'materials/tools/toolsblocklight.vtf': b'blocklight texture',
            'materials/tools/toolsclip.vmt': b'retail clip material',
            'materials/tools/toolsclip.vtf': b'retail clip texture',
            'materials/dev/unrelated.vmt': b'do not copy',
        }
        groups = {}
        for path, payload in files.items():
            folder, filename = path.rsplit('/', 1)
            name, extension = filename.rsplit('.', 1)
            groups.setdefault(extension, {}).setdefault(folder, {})[name] = payload
        tree = bytearray()
        for extension, folders in groups.items():
            tree += extension.encode() + b'\0'
            for folder, names in folders.items():
                tree += folder.encode() + b'\0'
                for name, payload in names.items():
                    tree += name.encode() + b'\0'
                    tree += struct.pack('<IHHIIH', zlib.crc32(payload), len(payload), DIR_ARCHIVE_INDEX, 0, 0, 0xffff)
                    tree += payload
                tree += b'\0'
            tree += b'\0'
        tree += b'\0'
        (retail / 'portal2/pak01_dir.vpk').write_bytes(struct.pack('<III', VPK_SIGNATURE, 1, len(tree)) + tree)
        return files

    return write
