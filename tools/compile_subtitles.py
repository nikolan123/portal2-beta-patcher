"""Compile a Source 1 closed-caption TXT file into a DAT database."""

from __future__ import annotations

import argparse
import os
import struct
import tempfile
import zlib
from pathlib import Path


MAGIC = int.from_bytes(b"VCCD", "little")
VERSION = 1
DIRECTORY_ALIGNMENT = 512
DEFAULT_BLOCK_SIZE = 4096
DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/patches/build_852_0/subtitles/closecaption_english.txt"
)


def parse_entries(text: str) -> list[tuple[str, str]]:
    """Read the Tokens object, rejecting malformed or unsupported syntax."""
    lexemes: list[tuple[str, bool, int]] = []
    pos, line = 0, 1
    while pos < len(text):
        char = text[pos]
        if char.isspace():
            line += char == "\n"
            pos += 1
        elif text.startswith("//", pos):
            end = text.find("\n", pos)
            pos = len(text) if end == -1 else end
        elif text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            if end == -1:
                raise ValueError(f"line {line}: unterminated comment")
            line += text[pos:end + 2].count("\n")
            pos = end + 2
        elif char in "{}":
            lexemes.append((char, False, line))
            pos += 1
        elif char == '"':
            start_line = line
            pos += 1
            value = []
            while pos < len(text) and text[pos] != '"':
                char = text[pos]
                if char in "\r\n\x00":
                    raise ValueError(f"line {line}: newline or NUL inside quoted string")
                if char == "\\" and pos + 1 < len(text) and text[pos + 1] in '\\"':
                    pos += 1
                    char = text[pos]
                value.append(char)
                pos += 1
            if pos == len(text):
                raise ValueError(f"line {start_line}: unterminated quoted string")
            pos += 1
            lexemes.append(("".join(value), True, start_line))
        else:
            raise ValueError(f"line {line}: unexpected character {char!r}")

    index = 0

    def take(value: str | None = None, quoted: bool | None = None) -> str:
        nonlocal index
        if index == len(lexemes):
            raise ValueError("unexpected end of file")
        actual, is_quoted, number = lexemes[index]
        if (value is not None and actual.lower() != value.lower()) or (
            quoted is not None and quoted != is_quoted
        ):
            raise ValueError(f"line {number}: expected {value or 'quoted string'}, got {actual!r}")
        index += 1
        return actual

    take("lang", True)
    take("{", False)
    entries: list[tuple[str, str]] = []
    found_tokens = False
    while index < len(lexemes) and lexemes[index][:2] != ("}", False):
        key = take(quoted=True)
        if key.lower() == "language":
            take(quoted=True)
        elif key.lower() == "tokens" and not found_tokens:
            found_tokens = True
            take("{", False)
            while index < len(lexemes) and lexemes[index][:2] != ("}", False):
                token = take(quoted=True)
                caption = take(quoted=True)
                if not token:
                    raise ValueError("empty caption token")
                entries.append((token, caption))
            take("}", False)
        else:
            raise ValueError(f"unexpected or repeated object {key!r}")
    take("}", False)
    if index != len(lexemes):
        raise ValueError(f"line {lexemes[index][2]}: unexpected trailing content")
    if not entries:
        raise ValueError("no caption tokens found")
    return entries


def read_entries(path: Path) -> list[tuple[str, str]]:
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return parse_entries(raw.decode(encoding))


def effective_entries(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Last definition wins for repeated names; distinct CRC collisions are errors."""
    by_hash: dict[int, tuple[str, str]] = {}
    for token, caption in entries:
        token_hash = zlib.crc32(token.lower().encode("utf-8")) & 0xFFFFFFFF
        previous = by_hash.get(token_hash)
        if previous is not None and previous[0].lower() != token.lower():
            raise ValueError(f"CRC collision between {previous[0]!r} and {token!r}")
        if not token or "\x00" in token or "\x00" in caption:
            raise ValueError(f"empty token or embedded NUL in {token!r}")
        by_hash[token_hash] = (token, caption)
    return list(by_hash.values())


def compile_dat(
    entries: list[tuple[str, str]], block_size: int = DEFAULT_BLOCK_SIZE
) -> bytes:
    if block_size < 2 or block_size > 0xFFFF or block_size % 2:
        raise ValueError("block size must be even and between 2 and 65534")

    entries = effective_entries(entries)
    blocks: list[bytearray] = [bytearray()]
    directory: list[tuple[int, int, int, int]] = []
    for token, caption in entries:
        token_hash = zlib.crc32(token.lower().encode("utf-8")) & 0xFFFFFFFF
        encoded = caption.encode("utf-16-le") + b"\x00\x00"
        if len(encoded) > block_size:
            raise ValueError(
                f"caption {token!r} is {len(encoded)} bytes; maximum is {block_size}"
            )
        block = blocks[-1]
        if len(block) + len(encoded) > block_size:
            block = bytearray()
            blocks.append(block)
        offset = len(block)
        block.extend(encoded)
        directory.append((token_hash, len(blocks) - 1, offset, len(encoded)))

    directory_end = 24 + len(directory) * 12
    data_offset = (
        (directory_end + DIRECTORY_ALIGNMENT - 1)
        // DIRECTORY_ALIGNMENT
        * DIRECTORY_ALIGNMENT
    )
    header = struct.pack(
        "<6I", MAGIC, VERSION, len(blocks), block_size, len(directory), data_offset
    )
    directory_bytes = b"".join(struct.pack("<IIHH", *entry) for entry in directory)
    padding = bytes(data_offset - len(header) - len(directory_bytes))
    data = b"".join(bytes(block).ljust(block_size, b"\x00") for block in blocks)
    return header + directory_bytes + padding + data


def decode_dat(data: bytes) -> dict[int, str]:
    """Validate the database and decode every directory entry."""
    if len(data) < 24:
        raise ValueError("truncated DAT header")
    magic, version, blocks, block_size, count, start = struct.unpack_from("<6I", data)
    if (magic, version) != (MAGIC, VERSION):
        raise ValueError("unsupported DAT format")
    if not blocks or block_size < 2 or block_size > 65534 or block_size % 2:
        raise ValueError("invalid DAT block size or count")
    if start < 24 + count * 12 or start % DIRECTORY_ALIGNMENT:
        raise ValueError("invalid DAT directory offset")
    if len(data) != start + blocks * block_size:
        raise ValueError("invalid DAT length")
    result = {}
    for index in range(count):
        token_hash, block, offset, length = struct.unpack_from("<IIHH", data, 24 + index * 12)
        if block >= blocks or offset % 2 or length < 2 or length % 2 or offset + length > block_size:
            raise ValueError(f"invalid DAT entry {index}")
        if token_hash in result:
            raise ValueError(f"duplicate DAT hash in entry {index}")
        position = start + block * block_size + offset
        raw = data[position:position + length]
        if raw[-2:] != b"\x00\x00":
            raise ValueError(f"unterminated DAT caption {index}")
        caption = raw[:-2].decode("utf-16-le")
        if "\x00" in caption:
            raise ValueError(f"embedded NUL in DAT caption {index}")
        result[token_hash] = caption
    return result


def atomic_write(output: Path, data: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile a Source 1 closed-caption TXT file into a DAT database."
    )
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_SOURCE,
                        help="UTF-16 or UTF-8 TXT (default: bundled English subtitles)")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="output DAT path (default: source path with a .dat extension)",
    )
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    parser.add_argument("--check", action="store_true", help="verify that the DAT matches the TXT without writing")
    args = parser.parse_args()

    output = args.output or args.source.with_suffix(".dat")
    try:
        if args.source.resolve() == output.resolve() or (
            output.exists() and args.source.samefile(output)
        ):
            raise ValueError("output must not overwrite the source TXT")
        source_entries = read_entries(args.source)
        entries = effective_entries(source_entries)
        compiled = compile_dat(entries, args.block_size)
        expected = {zlib.crc32(token.lower().encode("utf-8")) & 0xFFFFFFFF: caption
                    for token, caption in entries}
        if decode_dat(compiled) != expected:
            raise ValueError("compiled captions failed verification")
        if args.check:
            if not output.is_file() or output.read_bytes() != compiled:
                parser.exit(1, f"DAT is missing or out of date: {output}\n")
            print(f"DAT matches TXT exactly ({len(entries)} caption tokens)")
            return 0
        atomic_write(output, compiled)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Compiled {len(entries)} caption tokens")
    if len(source_entries) != len(entries):
        print(f"Duplicate definitions resolved: {len(source_entries) - len(entries)}")
    print(f"DAT: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
