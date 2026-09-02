from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os
import struct
from threading import Event
from typing import BinaryIO, Callable, Iterator
import zlib

from models import BuildCancelled


VPK_SIGNATURE = 0x55AA1234
DIR_ARCHIVE_INDEX = 0x7FFF


class VPKError(RuntimeError):
    pass


@dataclass(frozen=True)
class VPKEntry:
    path: str
    crc32: int
    preload: bytes
    archive_index: int
    offset: int
    length: int


def _read_cstring(stream: BinaryIO, end: int) -> str:
    data = bytearray()
    while stream.tell() < end:
        char = stream.read(1)
        if not char:
            raise VPKError("VPK tree string is truncated")
        if char == b"\0":
            return data.decode("utf-8", "surrogateescape")
        data.extend(char)
    raise VPKError("VPK tree string crosses the tree boundary")


def safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ":" in normalized or "\0" in normalized:
        raise VPKError(f"Unsafe VPK path: {value!r}")
    if any(part in ("", ".", "..") for part in path.parts):
        raise VPKError(f"Unsafe VPK path: {value!r}")
    return path


class VPKArchive:
    def __init__(self, directory_file: Path):
        self.directory_file = directory_file.resolve()
        self.header_size = 0
        self.tree_size = 0
        self.data_section_offset = 0
        self.version = 0
        self.entries = list(self._read_tree())

    def _read_tree(self) -> Iterator[VPKEntry]:
        with self.directory_file.open("rb") as stream:
            first = stream.read(12)
            if len(first) != 12:
                raise VPKError(f"VPK header is truncated: {self.directory_file}")
            signature, version, tree_size = struct.unpack("<III", first)
            if signature != VPK_SIGNATURE or version not in (1, 2):
                raise VPKError(f"Unsupported VPK header: {self.directory_file}")
            self.version = version
            self.tree_size = tree_size
            if version == 1:
                self.header_size = 12
            else:
                rest = stream.read(16)
                if len(rest) != 16:
                    raise VPKError("VPK v2 header is truncated")
                _file_data, _archive_md5, _other_md5, _signature = struct.unpack("<4I", rest)
                self.header_size = 28
            tree_end = self.header_size + tree_size
            self.data_section_offset = tree_end

            while stream.tell() < tree_end:
                extension = _read_cstring(stream, tree_end)
                if extension == "":
                    break
                while stream.tell() < tree_end:
                    folder = _read_cstring(stream, tree_end)
                    if folder == "":
                        break
                    while stream.tell() < tree_end:
                        name = _read_cstring(stream, tree_end)
                        if name == "":
                            break
                        fixed = stream.read(18)
                        if len(fixed) != 18:
                            raise VPKError("VPK entry is truncated")
                        crc, preload_size, archive_index, offset, length, terminator = struct.unpack("<IHHIIH", fixed)
                        if terminator != 0xFFFF:
                            raise VPKError("VPK entry has an invalid terminator")
                        preload = stream.read(preload_size)
                        if len(preload) != preload_size:
                            raise VPKError("VPK preload data is truncated")
                        filename = name if extension == " " else f"{name}.{extension}"
                        full = filename if folder == " " else f"{folder}/{filename}"
                        safe_relative_path(full)
                        yield VPKEntry(full, crc, preload, archive_index, offset, length)

    def _segment_path(self, archive_index: int) -> Path:
        name = self.directory_file.name
        if not name.casefold().endswith("_dir.vpk"):
            raise VPKError(f"Cannot derive VPK segment name from {name}")
        return self.directory_file.with_name(f"{name[:-8]}_{archive_index:03d}.vpk")

    def read_entry(self, entry: VPKEntry) -> bytes:
        if entry.archive_index == DIR_ARCHIVE_INDEX:
            source_path = self.directory_file
            source_offset = self.data_section_offset + entry.offset
        else:
            source_path = self._segment_path(entry.archive_index)
            source_offset = entry.offset
        try:
            with source_path.open("rb") as stream:
                stream.seek(source_offset)
                payload = stream.read(entry.length)
        except FileNotFoundError as error:
            raise VPKError(f"Missing VPK segment: {source_path.name}") from error
        if len(payload) != entry.length:
            raise VPKError(f"VPK entry is truncated: {entry.path}")
        result = entry.preload + payload
        if zlib.crc32(result) & 0xFFFFFFFF != entry.crc32:
            raise VPKError(f"VPK CRC mismatch: {entry.path}")
        return result

    def extract_to(
        self,
        destination: Path,
        cancel: Event,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[int, int, int]:
        root = destination.resolve()
        root.mkdir(parents=True, exist_ok=True)
        written = skipped = byte_count = 0
        for index, entry in enumerate(self.entries, start=1):
            if cancel.is_set():
                raise BuildCancelled("Build cancelled")
            if progress and (index == 1 or index == len(self.entries) or index % 250 == 0):
                progress(index, len(self.entries), entry.path)
            relative = safe_relative_path(entry.path)
            target = root.joinpath(*relative.parts)
            if os.path.commonpath((root, target.resolve())) != str(root):
                raise VPKError(f"VPK path escapes output: {entry.path}")
            if target.exists():
                skipped += 1
                continue
            data = self.read_entry(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            written += 1
            byte_count += len(data)
        return written, skipped, byte_count
