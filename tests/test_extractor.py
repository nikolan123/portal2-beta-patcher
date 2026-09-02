from __future__ import annotations

import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB
import pytest

from extractor import Blob, DEPOT_852_KEY, ExtractionError, decode_chunk, parse_file_table, parse_manifest, safe_output_path


def make_blob(values: dict[int, bytes]) -> bytes:
    body = bytearray()
    for key, value in values.items():
        key_data = struct.pack("<I", key)
        body.extend(struct.pack("<HI", len(key_data), len(value)))
        body.extend(key_data)
        body.extend(value)
    return struct.pack("<HII", 0x5001, 10 + len(body), 0) + body


def test_blob_keys_and_compression():
    plain = make_blob({4: b"table"})
    assert Blob(plain).get(4) == b"table"
    compressed = struct.pack("<HQQH", 0x4301, len(zlib.compress(plain)), len(plain), 9) + zlib.compress(plain)
    assert Blob(compressed).get(4) == b"table"


def test_chunk_modes():
    original = b"hello" * 200
    compressed = zlib.compress(original)
    assert decode_chunk(original, 0) == original
    assert decode_chunk(compressed, 1) == original

    encryptor = Cipher(algorithms.AES(DEPOT_852_KEY), CFB(bytes(16))).encryptor()
    encrypted_compressed = encryptor.update(compressed)
    wrapped = struct.pack("<II", len(encrypted_compressed), len(original)) + encrypted_compressed
    assert decode_chunk(wrapped, 2) == original

    encryptor = Cipher(algorithms.AES(DEPOT_852_KEY), CFB(bytes(16))).encryptor()
    encrypted = encryptor.update(original)
    assert decode_chunk(encrypted, 3) == original


def test_file_table_version_zero():
    header = struct.pack("<8I", 0x34457234, 0, 1, 1, 0x20, 0x30, 0x8000, 1)
    group = struct.pack("<4I", 7, 1, 0x30, 0)
    mapping = struct.pack("<III", 123, 456, (1 << 24) | 1)
    block = struct.pack("<II", 99, 0x12345678)
    table = header + group + mapping + block + struct.pack("<I", 0x34457234)
    result = parse_file_table(table)[7]
    assert (result.file_size, result.offset, result.mode) == (123, 456, 1)
    assert result.blocks[0].compressed_size == 99


def test_manifest_paths_and_checksum():
    strings = b"file.txt\0"
    root = struct.pack("<7I", 0, 0, 0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 1)
    file_node = struct.pack("<7I", 0, 4, 9, 1, 0, 0xFFFFFFFF, 0xFFFFFFFF)
    binary_size = 56 + len(root) + len(file_node) + len(strings)
    header = list((4, 852, 0, 2, 1, 0x8000, binary_size, len(strings), 0, 0, 0, 0, 0, 0))
    raw = bytearray(struct.pack("<14I", *header) + root + file_node + strings)
    struct.pack_into("<I", raw, 52, zlib.adler32(raw, 0) & 0xFFFFFFFF)
    files, metadata = parse_manifest(bytes(raw))
    assert files[0].path == "file.txt"
    assert files[0].file_id == 9
    assert metadata["app_id"] == 852


def test_unsafe_output_paths(tmp_path):
    with pytest.raises(ExtractionError):
        safe_output_path(tmp_path, "../escape.txt")
    with pytest.raises(ExtractionError):
        safe_output_path(tmp_path, "C:/escape.txt")
