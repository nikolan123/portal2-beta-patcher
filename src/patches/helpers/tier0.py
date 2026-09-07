import hashlib
import struct
from patches.base import PatchError

ALLOCATOR_OLD = bytes.fromhex("83 FE 20 7C EE")
ALLOCATOR_NEW = bytes.fromhex("83 FE 80 72 EE")

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def p16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value)


def p32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def align(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def patch_tier0(
    original: bytes,
    *,
    old_table_address: int,
    expected_reference_offsets: list[int],
    expected_build: str,
) -> bytes:
    data = bytearray(original)
    pe = u32(data, 0x3C)
    if data[pe : pe + 4] != b"PE\0\0":
        raise PatchError("tier0.dll has an invalid PE signature")

    coff = pe + 4
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    if u16(data, optional) != 0x10B or section_count != 5:
        raise PatchError(f"tier0.dll is not the expected 32-bit {expected_build} image")

    image_base = u32(data, optional + 28)
    section_alignment = u32(data, optional + 32)
    file_alignment = u32(data, optional + 36)
    size_of_headers = u32(data, optional + 60)
    section_table = optional + optional_size
    new_header = section_table + section_count * 40
    if new_header + 40 > size_of_headers:
        raise PatchError("tier0.dll has no room for the thread-table section")

    last_virtual_end = 0
    last_raw_end = 0
    for index in range(section_count):
        header = section_table + index * 40
        virtual_size = u32(data, header + 8)
        virtual_address = u32(data, header + 12)
        raw_size = u32(data, header + 16)
        raw_pointer = u32(data, header + 20)
        last_virtual_end = max(last_virtual_end, virtual_address + max(virtual_size, raw_size))
        last_raw_end = max(last_raw_end, raw_pointer + raw_size)
    if last_raw_end != len(data):
        raise PatchError("tier0.dll has an unexpected section layout")

    allocator_offset = data.find(ALLOCATOR_OLD)
    if allocator_offset < 0 or data.find(ALLOCATOR_OLD, allocator_offset + 1) >= 0:
        raise PatchError("tier0.dll allocator signature was not found exactly once")
    data[allocator_offset : allocator_offset + len(ALLOCATOR_NEW)] = ALLOCATOR_NEW

    old_address = struct.pack("<I", old_table_address)
    references = []
    offset = data.find(old_address)
    while offset >= 0:
        references.append(offset)
        offset = data.find(old_address, offset + 1)
    if references != expected_reference_offsets:
        raise PatchError("tier0.dll has unexpected thread-table references")

    table_size = 0x80
    new_virtual_address = align(last_virtual_end, section_alignment)
    new_raw_pointer = align(last_raw_end, file_alignment)
    new_raw_size = align(table_size, file_alignment)
    new_absolute_address = image_base + new_virtual_address
    for reference in references:
        p32(data, reference, new_absolute_address)

    p16(data, coff + 2, section_count + 1)
    p32(data, optional + 8, u32(data, optional + 8) + new_raw_size)
    p32(data, optional + 56, align(new_virtual_address + table_size, section_alignment))
    data[new_header : new_header + 40] = b"\0" * 40
    data[new_header : new_header + 4] = b".tid"
    p32(data, new_header + 8, table_size)
    p32(data, new_header + 12, new_virtual_address)
    p32(data, new_header + 16, new_raw_size)
    p32(data, new_header + 20, new_raw_pointer)
    p32(data, new_header + 36, 0xC0000040)
    if len(data) < new_raw_pointer:
        data.extend(b"\0" * (new_raw_pointer - len(data)))
    data.extend(b"\0" * new_raw_size)
    return bytes(data)


