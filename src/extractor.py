from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import struct
from threading import Event
from typing import Callable
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB

from models import BuildCancelled, ProgressEvent


DEPOT_852_KEY = bytes.fromhex("e223775bc18bfcb008ee114955704507")
MAX_CHUNK = 0x10000
MAX_DECOMPRESSED_CHUNK = 0x8000


class ExtractionError(RuntimeError):
    pass


class Blob:
    def __init__(self, raw: bytes):
        if len(raw) < 10:
            raise ExtractionError("BLOB is shorter than its header")
        magic = struct.unpack_from("<H", raw)[0]
        if magic == 0x4301:
            raw = self._decompress(raw)
            magic = struct.unpack_from("<H", raw)[0]
        if magic != 0x5001:
            raise ExtractionError(f"Unsupported BLOB magic 0x{magic:04x}")
        self.raw = raw
        self.total_size, self.slack_size = struct.unpack_from("<II", raw, 2)
        if self.total_size > len(raw) or self.total_size < 10:
            raise ExtractionError("Invalid BLOB total size")
        self.values: dict[bytes, bytes] = {}
        cursor = 10
        while cursor < self.total_size:
            if cursor + 6 > self.total_size:
                raise ExtractionError("Truncated BLOB entry header")
            key_size, value_size = struct.unpack_from("<HI", raw, cursor)
            cursor += 6
            end = cursor + key_size + value_size
            if end > self.total_size:
                raise ExtractionError("Truncated BLOB entry")
            key = raw[cursor : cursor + key_size]
            cursor += key_size
            self.values[key] = raw[cursor : cursor + value_size]
            cursor += value_size

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        if len(raw) < 20:
            raise ExtractionError("Compressed BLOB is shorter than its header")
        _packed_size, unpacked_size, _level = struct.unpack_from("<QQH", raw, 2)
        try:
            result = zlib.decompress(raw[20:])
        except zlib.error as error:
            raise ExtractionError(f"Compressed BLOB could not be decompressed: {error}") from error
        if len(result) != unpacked_size:
            raise ExtractionError("Compressed BLOB unpacked size mismatch")
        return result

    def get(self, numeric_key: int) -> bytes:
        key = struct.pack("<I", numeric_key)
        try:
            return self.values[key]
        except KeyError as error:
            raise ExtractionError(f"BLOB is missing key {numeric_key}") from error


@dataclass(frozen=True)
class Block:
    compressed_size: int
    checksum: int


@dataclass(frozen=True)
class FileLocation:
    file_id: int
    file_size: int
    offset: int
    mode: int
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ManifestFile:
    file_id: int
    path: str
    flags: int


def parse_file_table(raw: bytes) -> dict[int, FileLocation]:
    if len(raw) < 32:
        raise ExtractionError("File table is truncated")
    magic, version, block_groups, item_count, offset1, offset2, block_size, largest = struct.unpack_from(
        "<8I", raw, 0
    )
    if magic != 0x34457234 or block_size != 0x8000:
        raise ExtractionError("Invalid Steam 2 file table")
    if version not in (0, 1):
        raise ExtractionError(f"Unsupported file table version {version}")
    if offset1 != 0x20 or offset2 != 0x20 + 0x10 * block_groups:
        raise ExtractionError("Invalid file table offsets")
    if offset2 > len(raw):
        raise ExtractionError("File table group list is truncated")

    groups = [struct.unpack_from("<4I", raw, 0x20 + index * 16) for index in range(block_groups)]
    result: dict[int, FileLocation] = {}
    actual_items = 0
    largest_actual = 0
    for first_id, count, cursor, _unused in groups:
        if cursor > len(raw):
            raise ExtractionError("File table group offset is outside the table")
        actual_items += count
        for file_id in range(first_id, first_id + count):
            mapping_size = 12 if version == 0 else 20
            if cursor + mapping_size > len(raw):
                raise ExtractionError("File mapping is truncated")
            if version == 0:
                file_size, offset, mode_blocks = struct.unpack_from("<III", raw, cursor)
            else:
                file_size, offset, mode_blocks = struct.unpack_from("<QQI", raw, cursor)
            cursor += mapping_size
            mode = mode_blocks >> 24
            block_count = mode_blocks & 0x00FFFFFF
            if mode not in (0, 1, 2, 3):
                raise ExtractionError(f"File {file_id} has unsupported mode {mode}")
            if cursor + block_count * 8 > len(raw):
                raise ExtractionError("File block list is truncated")
            blocks = tuple(Block(*struct.unpack_from("<II", raw, cursor + i * 8)) for i in range(block_count))
            cursor += block_count * 8
            result[file_id] = FileLocation(file_id, file_size, offset, mode, blocks)
            largest_actual = max(largest_actual, block_count)

    footer_offsets = []
    for _first_id, count, cursor, _unused in groups:
        for _ in range(count):
            if version == 0:
                mode_blocks = struct.unpack_from("<I", raw, cursor + 8)[0]
                cursor += 12
            else:
                mode_blocks = struct.unpack_from("<I", raw, cursor + 16)[0]
                cursor += 20
            cursor += (mode_blocks & 0x00FFFFFF) * 8
        footer_offsets.append(cursor)
    footer_offset = max(footer_offsets, default=offset2)
    if footer_offset + 4 > len(raw) or struct.unpack_from("<I", raw, footer_offset)[0] != magic:
        raise ExtractionError("Invalid file table footer")
    if actual_items != item_count or largest_actual != largest:
        raise ExtractionError("File table counts do not match its header")
    return result


def parse_manifest(raw: bytes) -> tuple[list[ManifestFile], dict[str, int]]:
    if len(raw) < 56:
        raise ExtractionError("Manifest is truncated")
    header = struct.unpack_from("<14I", raw, 0)
    version, app_id, version_id, node_count, file_count, block_size, binary_size, string_size = header[:8]
    if version not in (3, 4):
        raise ExtractionError(f"Unsupported manifest version {version}")
    if binary_size != len(raw):
        raise ExtractionError("Manifest size does not match its header")
    node_bytes = node_count * 28
    string_start = 56 + node_bytes
    if string_start + string_size > len(raw):
        raise ExtractionError("Manifest string table is truncated")

    checksum_data = bytearray(raw)
    expected_checksum = header[13]
    struct.pack_into("<II", checksum_data, 48, 0, 0)
    if zlib.adler32(checksum_data, 0) & 0xFFFFFFFF != expected_checksum:
        raise ExtractionError("Manifest checksum is invalid")

    nodes = [struct.unpack_from("<7I", raw, 56 + index * 28) for index in range(node_count)]
    strings = raw[string_start : string_start + string_size]

    def read_name(offset: int) -> str:
        if offset >= len(strings):
            raise ExtractionError("Manifest name offset is invalid")
        end = strings.find(b"\0", offset)
        if end < 0:
            raise ExtractionError("Manifest name is not terminated")
        return strings[offset:end].decode("utf-8", "surrogateescape")

    files: list[ManifestFile] = []
    for index, node in enumerate(nodes):
        name_offset, _size, file_id, flags, parent, _sibling, _child = node
        components: list[str] = []
        current = index
        visited: set[int] = set()
        while nodes[current][4] != 0xFFFFFFFF:
            if current in visited or current >= len(nodes):
                raise ExtractionError("Manifest parent chain is invalid")
            visited.add(current)
            components.append(read_name(nodes[current][0]))
            parent_index = nodes[current][4]
            if parent_index >= len(nodes):
                raise ExtractionError("Manifest parent index is invalid")
            current = parent_index
        path = "/".join(reversed([item for item in components if item]))
        if flags:
            files.append(ManifestFile(file_id, path, flags))
    return files, {
        "manifest_version": version,
        "app_id": app_id,
        "version_id": version_id,
        "file_count": file_count,
        "block_size": block_size,
    }


def safe_output_path(root: Path, manifest_path: str) -> Path:
    normalized = manifest_path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ":" in normalized or "\0" in normalized:
        raise ExtractionError(f"Unsafe manifest path: {manifest_path!r}")
    if any(part in ("", ".", "..") for part in pure.parts):
        raise ExtractionError(f"Unsafe manifest path: {manifest_path!r}")
    candidate = root.joinpath(*pure.parts)
    root_resolved = root.resolve()
    if os.path.commonpath((root_resolved, candidate.resolve())) != str(root_resolved):
        raise ExtractionError(f"Manifest path escapes output: {manifest_path!r}")
    return candidate


def decode_chunk(data: bytes, mode: int, key: bytes = DEPOT_852_KEY) -> bytes:
    if len(data) > MAX_CHUNK:
        raise ExtractionError("Compressed chunk exceeds the Steam 2 maximum")
    if not data:
        return b""
    if mode == 0:
        return data
    if mode == 1:
        try:
            output = zlib.decompress(data)
        except zlib.error as error:
            raise ExtractionError(f"Chunk decompression failed: {error}") from error
    elif mode == 2:
        if len(data) < 8:
            raise ExtractionError("Encrypted compressed chunk has no header")
        _encrypted_size, expected_size = struct.unpack_from("<II", data)
        decrypted = Cipher(algorithms.AES(key), CFB(bytes(16))).decryptor().update(data[8:])
        try:
            output = zlib.decompress(decrypted)
        except zlib.error as error:
            raise ExtractionError(f"Encrypted chunk decompression failed: {error}") from error
        if len(output) != expected_size:
            raise ExtractionError("Encrypted chunk decompressed size mismatch")
    elif mode == 3:
        output = Cipher(algorithms.AES(key), CFB(bytes(16))).decryptor().update(data)
    else:
        raise ExtractionError(f"Unsupported chunk mode {mode}")
    if mode in (1, 2) and len(output) > MAX_DECOMPRESSED_CHUNK:
        raise ExtractionError("Decompressed chunk exceeds the Steam 2 maximum")
    return output


def extract_depot(
    blob_path: Path,
    dat_path: Path,
    output: Path,
    emit: Callable[[ProgressEvent], None],
    cancel: Event,
) -> dict[str, int]:
    top = Blob(blob_path.read_bytes())
    locations = parse_file_table(top.get(4))
    manifest_outer = Blob(top.get(3))
    manifest_files, metadata = parse_manifest(manifest_outer.get(0))
    dat_size = dat_path.stat().st_size
    total = sum(sum(block.compressed_size for block in locations[item.file_id].blocks) for item in manifest_files if item.file_id in locations)
    completed = 0
    written_files = 0
    output.mkdir(parents=True, exist_ok=False)

    with dat_path.open("rb") as dat_stream:
        for item in manifest_files:
            if cancel.is_set():
                raise BuildCancelled("Build cancelled")
            location = locations.get(item.file_id)
            if location is None:
                raise ExtractionError(f"Manifest file ID {item.file_id} has no DAT mapping")
            destination = safe_output_path(output, item.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            cursor = location.offset
            bytes_written = 0
            with destination.open("xb") as target:
                for block in location.blocks:
                    if cancel.is_set():
                        raise BuildCancelled("Build cancelled")
                    if cursor + block.compressed_size > dat_size:
                        raise ExtractionError(f"DAT range for {item.path} is outside the file")
                    dat_stream.seek(cursor)
                    chunk = dat_stream.read(block.compressed_size)
                    if len(chunk) != block.compressed_size:
                        raise ExtractionError(f"DAT chunk for {item.path} is truncated")
                    decoded = decode_chunk(chunk, location.mode)
                    target.write(decoded)
                    bytes_written += len(decoded)
                    cursor += block.compressed_size
                    completed += block.compressed_size
                    emit(ProgressEvent("extract", completed, max(total, 1), f"Extracting {item.path}"))
            if bytes_written != location.file_size:
                raise ExtractionError(
                    f"Extracted size mismatch for {item.path}: expected {location.file_size}, got {bytes_written}"
                )
            written_files += 1
    return {**metadata, "written_files": written_files, "compressed_bytes": total}
