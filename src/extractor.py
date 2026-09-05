from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import struct
from threading import Event
from typing import Callable
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.decrepit.ciphers.modes import CFB

from models import BuildCancelled, ProgressEvent, RevisionInput


# Portal 2 keys from steam2-winfsp: https://github.com/dr3murr/steam2-winfsp/blob/main/src/depot_keys.cpp
PORTAL2_DEPOT_KEYS = {
    841: bytes.fromhex("7bd71e1b45508b6edd8a8ae840f335ba"),
    852: bytes.fromhex("e223775bc18bfcb008ee114955704507"),
}
PORTAL2_DEPOT_IDS = frozenset({841, 843, 852})
ARCHIVE_NAME = re.compile(
    r"^(?P<depot>\d+)_(?P<version>\d+)_(?P<crc>[0-9a-fA-F]{8})_"
    r"(?P<sha>[0-9a-fA-F]{64})\.(?P<kind>blob|dat)$",
    re.IGNORECASE,
)
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
        if self.total_size > len(raw) or self.total_size < 10 or self.slack_size > len(raw) - self.total_size:
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
            if key in self.values:
                raise ExtractionError("BLOB contains a duplicate key")
            self.values[key] = raw[cursor : cursor + value_size]
            cursor += value_size

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        if len(raw) < 20:
            raise ExtractionError("Compressed BLOB is shorter than its header")
        packed_size, unpacked_size, _level = struct.unpack_from("<QQH", raw, 2)
        payload = raw[20:]
        if packed_size not in (len(payload), len(raw)):
            raise ExtractionError("Compressed BLOB packed size mismatch")
        try:
            result = zlib.decompress(payload)
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

    def get_u32(self, numeric_key: int) -> int:
        value = self.get(numeric_key)
        if len(value) != 4:
            raise ExtractionError(f"BLOB key {numeric_key} is not a 32-bit integer")
        return struct.unpack("<I", value)[0]

    def get_u64(self, numeric_key: int) -> int:
        value = self.get(numeric_key)
        if len(value) != 8:
            raise ExtractionError(f"BLOB key {numeric_key} is not a 64-bit integer")
        return struct.unpack("<Q", value)[0]


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
    size: int


@dataclass(frozen=True)
class ArchiveName:
    depot_id: int
    version: int
    crc: int
    sha256: str
    kind: str


@dataclass(frozen=True)
class BlobMetadata:
    depot_id: int
    version: int
    crc: int
    path: Path
    sha256: str
    parent_crc: int
    expected_dat_size: int
    extracted_size: int
    encrypted: bool
    runnable: bool


@dataclass(frozen=True)
class CatalogTarget:
    depot_id: int
    version: int
    crc: int
    blob_path: Path
    ready: bool
    reason: str
    chain: tuple[RevisionInput, ...] = ()
    needs_custom_key: bool = False
    runnable: bool = False
    estimated_size: int = 0

    @property
    def label(self) -> str:
        suffix = (
            f" - ~{format_byte_size(self.estimated_size)}"
            if self.ready
            else f" - {self.reason}"
        )
        return f"{self.depot_id} version {self.version} [{self.crc:08x}]{suffix}"


def format_byte_size(size: int) -> str:
    value = float(size)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("Unreachable")


def has_runnable_manifest(paths: set[str]) -> bool:
    normalized = {path.replace("\\", "/").lower() for path in paths}
    has_executable = "hl2.exe" in normalized or "portal2.exe" in normalized
    return has_executable and "portal2/gameinfo.txt" in normalized


def has_runnable_layout(root: Path) -> bool:
    has_executable = (root / "hl2.exe").is_file() or (root / "portal2.exe").is_file()
    return has_executable and (root / "portal2" / "GameInfo.txt").is_file()


def parse_archive_name(path: Path) -> ArchiveName | None:
    match = ARCHIVE_NAME.fullmatch(path.name)
    if not match:
        return None
    return ArchiveName(
        int(match.group("depot")),
        int(match.group("version")),
        int(match.group("crc"), 16),
        match.group("sha").lower(),
        match.group("kind").lower(),
    )


def inspect_blob(path: Path, name: ArchiveName | None = None) -> BlobMetadata:
    parsed_name = name or parse_archive_name(path)
    if parsed_name is None or parsed_name.kind != "blob":
        raise ExtractionError(f"Invalid Steam 2 BLOB filename: {path.name}")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != parsed_name.sha256:
        raise ExtractionError("BLOB SHA-256 does not match its filename")
    top = Blob(payload)
    depot_format = top.get_u32(0)
    if depot_format not in (3, 4):
        raise ExtractionError(f"Unsupported depot BLOB format {depot_format}")
    expected_dat_size = top.get_u32(13) if depot_format == 3 else top.get_u64(13)
    manifest_outer = Blob(top.get(3))
    files, manifest = parse_manifest(manifest_outer.get(0))
    if manifest["app_id"] != parsed_name.depot_id or manifest["version_id"] != parsed_name.version:
        raise ExtractionError("Manifest identity does not match the archive filename")
    locations = parse_file_table(top.get(4))
    encrypted = any(location.mode in (2, 3) for location in locations.values())
    return BlobMetadata(
        parsed_name.depot_id,
        parsed_name.version,
        parsed_name.crc,
        path,
        parsed_name.sha256,
        top.get_u32(12),
        expected_dat_size,
        sum(item.size for item in files),
        encrypted,
        has_runnable_manifest({item.path for item in files}),
    )


def _resolve_target(
    target: BlobMetadata,
    blobs: list[BlobMetadata],
    dats: list[tuple[Path, ArchiveName]],
) -> CatalogTarget:
    chain_newest: list[BlobMetadata] = []
    current = target
    visited: set[tuple[int, int]] = set()
    while True:
        identity = (current.version, current.crc)
        if identity in visited:
            return CatalogTarget(target.depot_id, target.version, target.crc, target.path, False, "Parent chain loops")
        visited.add(identity)
        chain_newest.append(current)
        if current.parent_crc == 0:
            break
        if current.version == 0:
            return CatalogTarget(target.depot_id, target.version, target.crc, target.path, False, "Version 0 names a parent")
        parents = [
            item for item in blobs
            if item.depot_id == current.depot_id
            and item.version == current.version - 1
            and item.crc == current.parent_crc
        ]
        if not parents:
            return CatalogTarget(
                target.depot_id, target.version, target.crc, target.path, False,
                f"Missing version {current.version - 1} BLOB ({current.parent_crc:08x})",
            )
        if len(parents) != 1:
            return CatalogTarget(
                target.depot_id, target.version, target.crc, target.path, False,
                f"Ambiguous version {current.version - 1} BLOB ({current.parent_crc:08x})",
            )
        current = parents[0]

    chain: list[RevisionInput] = []
    for blob in reversed(chain_newest):
        matches = [
            (path, name) for path, name in dats
            if name.depot_id == blob.depot_id
            and name.version == blob.version
            and path.stat().st_size == blob.expected_dat_size
        ]
        if not matches:
            return CatalogTarget(
                target.depot_id, target.version, target.crc, target.path, False,
                f"Missing version {blob.version} DAT ({blob.expected_dat_size:,} bytes)",
            )
        if len(matches) != 1:
            return CatalogTarget(
                target.depot_id, target.version, target.crc, target.path, False,
                f"Ambiguous version {blob.version} DAT",
            )
        dat_path, dat_name = matches[0]
        chain.append(RevisionInput(
            blob.depot_id,
            blob.version,
            blob.crc,
            blob.path,
            dat_path,
            blob.sha256,
            dat_name.sha256,
        ))

    encrypted = any(item.encrypted for item in chain_newest)
    needs_custom_key = encrypted and target.depot_id not in PORTAL2_DEPOT_KEYS
    reason = "Custom key required" if needs_custom_key else "Ready"
    return CatalogTarget(
        target.depot_id, target.version, target.crc, target.path,
        True, reason, tuple(chain), needs_custom_key, target.runnable, target.extracted_size,
    )


def scan_archive_catalog(folder: Path) -> list[CatalogTarget]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Archive folder does not exist: {folder}")
    named: list[tuple[Path, ArchiveName]] = []
    for path in folder.rglob("*"):
        if path.is_file() and (name := parse_archive_name(path)) is not None:
            named.append((path, name))

    blobs: list[BlobMetadata] = []
    failures: list[CatalogTarget] = []
    for path, name in named:
        if name.kind != "blob":
            continue
        if name.depot_id not in PORTAL2_DEPOT_IDS:
            failures.append(CatalogTarget(name.depot_id, name.version, name.crc, path, False, "Not a Portal 2 depot"))
            continue
        try:
            blobs.append(inspect_blob(path, name))
        except Exception as error:
            failures.append(CatalogTarget(name.depot_id, name.version, name.crc, path, False, f"Corrupt BLOB: {error}"))

    dats = [(path, name) for path, name in named if name.kind == "dat"]
    results: list[CatalogTarget] = []
    for blob in blobs:
        duplicates = [item for item in blobs if (item.depot_id, item.version, item.crc) == (blob.depot_id, blob.version, blob.crc)]
        if len(duplicates) != 1:
            results.append(CatalogTarget(blob.depot_id, blob.version, blob.crc, blob.path, False, "Ambiguous duplicate BLOB"))
        else:
            results.append(_resolve_target(blob, blobs, dats))
    return sorted(results + failures, key=lambda item: (item.depot_id, item.version, item.crc, str(item.blob_path)))


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
        name_offset, size, file_id, flags, parent, _sibling, _child = node
        components: list[str] = []
        current = index
        visited: set[int] = set()
        while True:
            if current in visited or current >= len(nodes):
                raise ExtractionError("Manifest parent chain is invalid")
            if nodes[current][4] == 0xFFFFFFFF:
                break
            visited.add(current)
            components.append(read_name(nodes[current][0]))
            parent_index = nodes[current][4]
            if parent_index >= len(nodes):
                raise ExtractionError("Manifest parent index is invalid")
            current = parent_index
        path = "/".join(reversed([item for item in components if item]))
        if flags:
            files.append(ManifestFile(file_id, path, flags, size))
    if len(files) != file_count:
        raise ExtractionError("Manifest file count does not match its nodes")
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


def decode_chunk(data: bytes, mode: int, key: bytes = PORTAL2_DEPOT_KEYS[852]) -> bytes:
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
        if len(key) != 16:
            raise ExtractionError("Encrypted chunks require a 16-byte depot key")
        if len(data) < 8:
            raise ExtractionError("Encrypted compressed chunk has no header")
        encrypted_size, expected_size = struct.unpack_from("<II", data)
        if encrypted_size != len(data) - 8:
            raise ExtractionError("Encrypted chunk header size mismatch")
        decrypted = Cipher(algorithms.AES(key), CFB(bytes(16))).decryptor().update(data[8:])
        try:
            output = zlib.decompress(decrypted)
        except zlib.error as error:
            raise ExtractionError(f"Encrypted chunk decompression failed: {error}") from error
        if len(output) != expected_size:
            raise ExtractionError("Encrypted chunk decompressed size mismatch")
    elif mode == 3:
        if len(key) != 16:
            raise ExtractionError("Encrypted chunks require a 16-byte depot key")
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


@dataclass(frozen=True)
class SourcedLocation:
    location: FileLocation
    dat_path: Path


def extract_revision_chain(
    chain: tuple[RevisionInput, ...],
    output: Path,
    emit: Callable[[ProgressEvent], None],
    cancel: Event,
    key: bytes | None = None,
    include_prefixes: tuple[str, ...] | None = None,
) -> dict[str, int]:
    if not chain:
        raise ExtractionError("The selected revision has no resolved ancestry")
    depot_id = chain[-1].depot_id
    if any(item.depot_id != depot_id for item in chain):
        raise ExtractionError("A revision chain cannot combine different depot IDs")
    depot_key = key or PORTAL2_DEPOT_KEYS.get(depot_id)

    mappings: dict[int, SourcedLocation] = {}
    manifest_files: list[ManifestFile] = []
    metadata: dict[str, int] = {}
    for index, revision in enumerate(chain):
        if cancel.is_set():
            raise BuildCancelled("Build cancelled")
        top = Blob(revision.blob_path.read_bytes())
        archive_name = parse_archive_name(revision.blob_path)
        if archive_name is None or archive_name.kind != "blob":
            raise ExtractionError(f"Invalid BLOB filename in revision {revision.version}")
        if (archive_name.depot_id, archive_name.version, archive_name.crc) != (
            revision.depot_id, revision.version, revision.crc
        ):
            raise ExtractionError(f"BLOB identity mismatch in revision {revision.version}")
        parent_crc = top.get_u32(12)
        expected_parent = 0 if index == 0 else chain[index - 1].crc
        if parent_crc != expected_parent:
            raise ExtractionError(f"Parent CRC mismatch in revision {revision.version}")
        if index and revision.version != chain[index - 1].version + 1:
            raise ExtractionError("Revision chain versions are not consecutive")
        locations = parse_file_table(top.get(4))
        if any(location.mode in (2, 3) for location in locations.values()) and depot_key is None:
            raise ExtractionError(f"Depot {depot_id} contains encrypted data and needs a 16-byte key")
        expected_size = top.get_u32(13) if top.get_u32(0) == 3 else top.get_u64(13)
        actual_size = revision.dat_path.stat().st_size
        if actual_size != expected_size:
            raise ExtractionError(
                f"DAT size mismatch for version {revision.version}: expected {expected_size}, got {actual_size}"
            )
        manifest_outer = Blob(top.get(3))
        current_manifest, current_metadata = parse_manifest(manifest_outer.get(0))
        if current_metadata["app_id"] != depot_id or current_metadata["version_id"] != revision.version:
            raise ExtractionError(f"Manifest identity mismatch in version {revision.version}")
        for file_id, location in locations.items():
            mappings[file_id] = SourcedLocation(location, revision.dat_path)
        if index == len(chain) - 1:
            manifest_files = current_manifest
            metadata = current_metadata

    if include_prefixes:
        prefixes = tuple(
            prefix.replace("\\", "/").strip("/").casefold() + "/"
            for prefix in include_prefixes
        )
        manifest_files = [
            item for item in manifest_files
            if item.path.replace("\\", "/").lstrip("/").casefold().startswith(prefixes)
        ]
        if not manifest_files:
            raise ExtractionError("The target manifest contains no files under the requested prefixes")

    missing = [item.file_id for item in manifest_files if item.file_id not in mappings]
    if missing:
        raise ExtractionError(f"Target manifest has file IDs with no ancestry mapping: {missing[:5]}")
    total = sum(
        sum(block.compressed_size for block in mappings[item.file_id].location.blocks)
        for item in manifest_files
    )
    completed = 0
    written_files = 0
    output.mkdir(parents=True, exist_ok=False)
    streams: dict[Path, object] = {}
    try:
        for item in manifest_files:
            if cancel.is_set():
                raise BuildCancelled("Build cancelled")
            sourced = mappings[item.file_id]
            location = sourced.location
            destination = safe_output_path(output, item.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            stream = streams.get(sourced.dat_path)
            if stream is None:
                stream = sourced.dat_path.open("rb")
                streams[sourced.dat_path] = stream
            cursor = location.offset
            bytes_written = 0
            with destination.open("xb") as target:
                for block in location.blocks:
                    if cancel.is_set():
                        raise BuildCancelled("Build cancelled")
                    stream.seek(cursor)
                    encoded = stream.read(block.compressed_size)
                    if len(encoded) != block.compressed_size:
                        raise ExtractionError(f"DAT chunk for {item.path} is truncated")
                    decoded = decode_chunk(encoded, location.mode, depot_key or bytes(16))
                    remaining = location.file_size - bytes_written
                    expected_chunk = min(MAX_DECOMPRESSED_CHUNK, remaining)
                    if len(decoded) != expected_chunk:
                        raise ExtractionError(
                            f"Decoded block size mismatch for {item.path}: expected {expected_chunk}, got {len(decoded)}"
                        )
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
    finally:
        for stream in streams.values():
            stream.close()
    return {
        **metadata,
        "written_files": written_files,
        "compressed_bytes": total,
        "revision_count": len(chain),
    }
