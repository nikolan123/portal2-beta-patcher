from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from threading import Event
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB
import pytest

from extractor import (
    PORTAL2_DEPOT_IDS,
    PORTAL2_DEPOT_KEYS,
    ExtractionError,
    extract_revision_chain,
    parse_archive_name,
    scan_archive_catalog,
)
from models import BuildCancelled, BuildInputs
from pipeline import BuildPipeline


def test_supported_portal2_depots_and_bundled_keys():
    assert PORTAL2_DEPOT_IDS == {841, 843, 852}
    assert set(PORTAL2_DEPOT_KEYS) == {841, 852}


def make_blob(values: dict[int, bytes]) -> bytes:
    body = bytearray()
    for key, value in values.items():
        body += struct.pack("<HI", 4, len(value)) + struct.pack("<I", key) + value
    return struct.pack("<HII", 0x5001, 10 + len(body), 0) + body


def make_manifest(depot: int, version: int, files: dict[int, str]) -> bytes:
    strings = bytearray(b"\0")
    nodes = [struct.pack("<7I", 0, 0, 0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 1 if files else 0xFFFFFFFF)]
    for file_id, path in files.items():
        offset = len(strings)
        strings += path.encode("utf-8") + b"\0"
        nodes.append(struct.pack("<7I", offset, 0, file_id, 1, 0, 0xFFFFFFFF, 0xFFFFFFFF))
    size = 56 + sum(map(len, nodes)) + len(strings)
    header = [4, depot, version, len(nodes), len(files), 0x8000, size, len(strings), 0, 0, 0, 0, 0, 0]
    raw = bytearray(struct.pack("<14I", *header) + b"".join(nodes) + strings)
    struct.pack_into("<I", raw, 52, zlib.adler32(raw, 0) & 0xFFFFFFFF)
    return bytes(raw)


def encode(payload: bytes, mode: int, key: bytes) -> bytes:
    if mode == 1:
        return zlib.compress(payload)
    if mode == 3:
        return Cipher(algorithms.AES(key), CFB(bytes(16))).encryptor().update(payload)
    raise AssertionError(mode)


def make_table(mappings: dict[int, bytes], mode: int, key: bytes) -> tuple[bytes, bytes]:
    encoded = {file_id: encode(payload, mode, key) for file_id, payload in mappings.items()}
    group_count = len(mappings)
    cursor = 0x20 + 0x10 * group_count
    dat = bytearray()
    groups = bytearray()
    records = bytearray()
    largest = 0
    for file_id, payload in mappings.items():
        chunk = encoded[file_id]
        groups += struct.pack("<4I", file_id, 1, cursor, 0)
        records += struct.pack("<III", len(payload), len(dat), (mode << 24) | 1)
        records += struct.pack("<II", len(chunk), zlib.adler32(payload) & 0xFFFFFFFF)
        cursor += 20
        dat += chunk
        largest = 1
    header = struct.pack(
        "<8I", 0x34457234, 0, group_count, len(mappings), 0x20,
        0x20 + 0x10 * group_count, 0x8000, largest,
    )
    return header + groups + records + struct.pack("<I", 0x34457234), bytes(dat)


def write_revision(
    folder: Path,
    depot: int,
    version: int,
    crc: int,
    parent_crc: int,
    manifest_files: dict[int, str],
    mappings: dict[int, bytes],
    mode: int = 1,
    key: bytes = PORTAL2_DEPOT_KEYS[852],
) -> tuple[Path, Path]:
    table, dat = make_table(mappings, mode, key)
    top = make_blob({
        0: struct.pack("<I", 3),
        3: make_blob({0: make_manifest(depot, version, manifest_files)}),
        4: table,
        12: struct.pack("<I", parent_crc),
        13: struct.pack("<I", len(dat)),
    })
    folder.mkdir(parents=True, exist_ok=True)
    blob_sha = hashlib.sha256(top).hexdigest()
    dat_sha = hashlib.sha256(dat).hexdigest()
    blob = folder / f"{depot}_{version}_{crc:08x}_{blob_sha}.blob"
    dat_path = folder / f"{depot}_{version}_{crc ^ 0x55:08x}_{dat_sha}.dat"
    blob.write_bytes(top)
    dat_path.write_bytes(dat)
    return blob, dat_path


def ready_target(folder: Path, version: int, crc: int):
    return next(
        item for item in scan_archive_catalog(folder)
        if item.version == version and item.crc == crc and item.ready
    )


def test_strict_archive_names_ignore_unrelated_dat(tmp_path):
    (tmp_path / "subtitles.dat").write_bytes(b"ignored")
    assert parse_archive_name(tmp_path / "subtitles.dat") is None
    assert scan_archive_catalog(tmp_path) == []


def test_complete_chain_inherits_and_replaces_mappings_and_uses_final_manifest(tmp_path):
    write_revision(tmp_path, 852, 0, 0x10, 0, {1: "kept.txt", 2: "removed.txt"}, {1: b"old", 2: b"gone"})
    write_revision(tmp_path, 852, 1, 0x11, 0x10, {1: "kept.txt", 3: "inherited.txt"}, {1: b"new", 3: b"parent"})
    write_revision(tmp_path, 852, 2, 0x12, 0x11, {1: "kept.txt", 3: "inherited.txt"}, {1: b"newest"})
    target = ready_target(tmp_path, 2, 0x12)
    assert [item.version for item in target.chain] == [0, 1, 2]

    output = tmp_path / "out"
    extract_revision_chain(target.chain, output, lambda _event: None, Event())

    assert (output / "kept.txt").read_bytes() == b"newest"
    assert (output / "inherited.txt").read_bytes() == b"parent"
    assert not (output / "removed.txt").exists()


def test_revision_chain_can_extract_only_one_manifest_folder(tmp_path):
    write_revision(
        tmp_path,
        852,
        0,
        0x13,
        0,
        {
            1: "portal2_tempcontent/materials/console/startup_loading.vtf",
            2: "portal2/unrelated.txt",
        },
        {1: b"loading image", 2: b"unrelated"},
    )
    target = ready_target(tmp_path, 0, 0x13)
    output = tmp_path / "filtered-out"

    result = extract_revision_chain(
        target.chain,
        output,
        lambda _event: None,
        Event(),
        include_prefixes=("portal2_tempcontent",),
    )

    assert result["written_files"] == 1
    assert (output / "portal2_tempcontent" / "materials" / "console" / "startup_loading.vtf").read_bytes() == b"loading image"
    assert not (output / "portal2").exists()


def test_missing_parent_and_missing_or_wrong_sized_dat_are_visible(tmp_path):
    write_revision(tmp_path, 852, 2, 0x22, 0x21, {1: "file.txt"}, {1: b"x"})
    target = next(item for item in scan_archive_catalog(tmp_path) if item.version == 2)
    assert not target.ready and "Missing version 1 BLOB" in target.reason

    other = tmp_path / "other"
    _blob, dat = write_revision(other, 852, 0, 0x30, 0, {1: "file.txt"}, {1: b"x"})
    dat.write_bytes(dat.read_bytes() + b"wrong")
    target = next(item for item in scan_archive_catalog(other) if item.version == 0)
    assert not target.ready and "Missing version 0 DAT" in target.reason


def test_duplicate_and_reset_branches_are_not_mixed(tmp_path):
    write_revision(tmp_path / "a", 852, 0, 0x40, 0, {1: "a.txt"}, {1: b"a"})
    blob_b, _dat_b = write_revision(
        tmp_path / "b", 852, 0, 0x41, 0, {1: "b.txt"}, {1: b"a much longer branch"}
    )
    write_revision(tmp_path / "a", 852, 1, 0x42, 0x40, {1: "a.txt"}, {1: b"a1"})
    write_revision(
        tmp_path / "b", 852, 1, 0x43, 0x41, {1: "b.txt"}, {1: b"a much longer branch version one"}
    )
    a = ready_target(tmp_path, 1, 0x42)
    b = ready_target(tmp_path, 1, 0x43)
    assert [item.crc for item in a.chain] == [0x40, 0x42]
    assert [item.crc for item in b.chain] == [0x41, 0x43]

    duplicate_dir = tmp_path / "duplicate"
    duplicate_dir.mkdir()
    (duplicate_dir / blob_b.name).write_bytes(blob_b.read_bytes())
    duplicate_results = [item for item in scan_archive_catalog(tmp_path) if item.crc == 0x41]
    assert duplicate_results and all(not item.ready for item in duplicate_results)


def test_encrypted_known_and_custom_keys(tmp_path):
    write_revision(tmp_path / "known", 852, 0, 0x50, 0, {1: "known.txt"}, {1: b"secret"}, mode=3)
    known = ready_target(tmp_path / "known", 0, 0x50)
    extract_revision_chain(known.chain, tmp_path / "known-out", lambda _event: None, Event())
    assert (tmp_path / "known-out" / "known.txt").read_bytes() == b"secret"

    custom_key = bytes.fromhex("00112233445566778899aabbccddeeff")
    write_revision(tmp_path / "custom", 843, 0, 0x51, 0, {1: "custom.txt"}, {1: b"secret"}, mode=3, key=custom_key)
    custom = ready_target(tmp_path / "custom", 0, 0x51)
    assert custom.needs_custom_key and custom.reason == "Custom key required"
    with pytest.raises(ExtractionError):
        extract_revision_chain(custom.chain, tmp_path / "bad-key", lambda _event: None, Event())
    extract_revision_chain(custom.chain, tmp_path / "custom-out", lambda _event: None, Event(), custom_key)
    assert (tmp_path / "custom-out" / "custom.txt").read_bytes() == b"secret"


def test_generic_pipeline_cleans_staging_when_cancelled(tmp_path):
    write_revision(
        tmp_path / "archives", 852, 0, 0x60, 0,
        {1: "file.txt", 2: "second.txt"}, {1: b"payload", 2: b"more"},
    )
    target = ready_target(tmp_path / "archives", 0, 0x60)
    output = tmp_path / "result"
    cancel = Event()

    def emit(event):
        if event.phase == "extract":
            cancel.set()

    final = target.chain[-1]
    inputs = BuildInputs(
        final.blob_path, final.dat_path, None, output, (), None,
        "generic", 852, 0, 0x60, target.chain, None,
    )
    with pytest.raises(BuildCancelled):
        BuildPipeline(emit, cancel).run(inputs)
    assert not output.exists()
    assert not list(tmp_path.glob(".result.partial-*"))
