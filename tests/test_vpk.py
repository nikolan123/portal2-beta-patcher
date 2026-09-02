from __future__ import annotations

import struct
import zlib

import pytest

from vpk import DIR_ARCHIVE_INDEX, VPKArchive, VPKError, VPK_SIGNATURE, safe_relative_path


def test_inline_vpk_v1(tmp_path):
    preload = b"hello "
    payload = b"world"
    complete = preload + payload
    entry = struct.pack(
        "<IHHIIH", zlib.crc32(complete) & 0xFFFFFFFF, len(preload), DIR_ARCHIVE_INDEX, 0, len(payload), 0xFFFF
    )
    tree = b"txt\0folder\0greeting\0" + entry + preload + b"\0\0\0"
    path = tmp_path / "test_dir.vpk"
    path.write_bytes(struct.pack("<III", VPK_SIGNATURE, 1, len(tree)) + tree + payload)
    archive = VPKArchive(path)
    assert archive.entries[0].path == "folder/greeting.txt"
    assert archive.read_entry(archive.entries[0]) == complete


def test_vpk_unsafe_paths():
    with pytest.raises(VPKError):
        safe_relative_path("../bad.txt")
    with pytest.raises(VPKError):
        safe_relative_path("C:/bad.txt")

