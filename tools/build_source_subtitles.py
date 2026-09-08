"""Build Source 1 subtitle TXT and DAT files from my private subtitling app's JSON"""

from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from collections import OrderedDict
from pathlib import Path


MAGIC = int.from_bytes(b"VCCD", "little")
VERSION = 1
DIRECTORY_ALIGNMENT = 512
DEFAULT_BLOCK_SIZE = 4096

SPEAKERS = {
    "glados": ("163,193,173", "GLaDOS"),
    "cavejohnson": ("205,149,117", "Cave Johnson"),
    "sphere001": ("29,172,214", "Sphere"),
    "sphere01": ("29,172,214", "Sphere"),
    "sphere02": ("29,172,214", "Sphere"),
    "curiosity": ("231,144,194", "Curiosity Core"),
}

LOCALIZATION_ENTRY = re.compile(
    r'^\s*"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"'
)


def caption_for(item: dict[str, object]) -> str:
    event = str(item["event"])
    transcript = str(item.get("transcript") or "").strip()
    if event.casefold() == "curiosity.hi":
        return f"<clr:205,129,40><I>{transcript}"
    prefix = event.partition(".")[0].lower()
    color, speaker = SPEAKERS.get(prefix, ("255,255,255", prefix or "Unknown"))
    return f"<clr:{color}>{speaker}: {transcript}"


def load_entries(
    source: Path, omitted_events: set[str] | None = None
) -> tuple[list[tuple[str, str]], dict[str, list[dict[str, object]]], int]:
    root = json.loads(source.read_text(encoding="utf-8"))
    items = root["items"] if isinstance(root, dict) else root
    entries: OrderedDict[str, str] = OrderedDict()
    collisions: dict[str, list[dict[str, object]]] = {}
    omitted = 0

    omitted_events = {event.casefold() for event in omitted_events or set()}

    for item in items:
        event = str(item.get("event") or "").strip()
        transcript = str(item.get("transcript") or "").strip()
        if event.casefold() in omitted_events:
            omitted += 1
            continue
        if not event or not transcript:
            omitted += 1
            continue
        caption = caption_for(item)
        folded = event.casefold()
        if folded in entries:
            collisions.setdefault(folded, []).append(item)
            continue
        entries[folded] = caption

    # Caption hashes are case-insensitive. Preserve the spelling used by the first occurrence, which is also the line selected for random-wave aliases.
    original_names: dict[str, str] = {}
    for item in items:
        event = str(item.get("event") or "").strip()
        original_names.setdefault(event.casefold(), event)
    return [(original_names[key], value) for key, value in entries.items()], collisions, omitted


def escape_keyvalues(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", " ")


def read_txt_entries(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-16").splitlines():
        match = LOCALIZATION_ENTRY.match(line)
        if not match or match.group(1).casefold() == "language":
            continue
        token, caption = match.groups()
        token = re.sub(r'\\(["\\])', r'\1', token)
        caption = re.sub(r'\\(["\\])', r'\1', caption)
        entries.append((token, caption))
    return entries


def unique_entries(groups: list[list[tuple[str, str]]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    hashes: set[int] = set()
    for group in groups:
        for token, caption in group:
            token_hash = zlib.crc32(token.lower().encode("utf-8")) & 0xFFFFFFFF
            if token_hash in hashes:
                continue
            hashes.add(token_hash)
            result.append((token, caption))
    return result


def write_txt(path: Path, entries: list[tuple[str, str]]) -> None:
    lines = ['"lang"', "{", '\t"Language" "english"', '\t"Tokens"', "\t{"]
    for token, caption in entries:
        lines.append(f'\t\t"{escape_keyvalues(token)}"\t"{escape_keyvalues(caption)}"')
    lines.extend(["\t}", "}", ""])
    path.write_text("\r\n".join(lines), encoding="utf-16")


def write_merged_txt(path: Path, base_path: Path, entries: list[tuple[str, str]]) -> None:
    text = base_path.read_text(encoding="utf-16")
    closings = list(re.finditer(r"(?m)^\s*}\s*$", text))
    if len(closings) < 2:
        raise ValueError(f"could not find the Tokens closing brace in {base_path}")
    insertion = "".join(
        f'\t\t"{escape_keyvalues(token)}"\t"{escape_keyvalues(caption)}"\r\n'
        for token, caption in entries
    )
    offset = closings[-2].start()
    merged = text[:offset] + insertion + text[offset:]
    path.write_text(merged, encoding="utf-16")


def build_dat(entries: list[tuple[str, str]], block_size: int = DEFAULT_BLOCK_SIZE) -> bytes:
    if block_size <= 0 or block_size > 0xFFFF:
        raise ValueError("block size must fit in an unsigned 16-bit caption offset")

    blocks: list[bytearray] = [bytearray()]
    directory: list[tuple[int, int, int, int]] = []

    for token, caption in entries:
        encoded = caption.encode("utf-16-le") + b"\x00\x00"
        if len(encoded) > block_size:
            raise ValueError(f"caption {token!r} is {len(encoded)} bytes; maximum is {block_size}")
        block = blocks[-1]
        if len(block) + len(encoded) > block_size:
            block = bytearray()
            blocks.append(block)
        offset = len(block)
        block.extend(encoded)
        token_hash = zlib.crc32(token.lower().encode("utf-8")) & 0xFFFFFFFF
        directory.append((token_hash, len(blocks) - 1, offset, len(encoded)))

    directory_end = 24 + len(directory) * 12
    data_offset = (directory_end + DIRECTORY_ALIGNMENT - 1) // DIRECTORY_ALIGNMENT * DIRECTORY_ALIGNMENT
    header = struct.pack(
        "<6I", MAGIC, VERSION, len(blocks), block_size, len(directory), data_offset
    )
    directory_bytes = b"".join(struct.pack("<IIHH", *entry) for entry in directory)
    padding = bytes(data_offset - len(header) - len(directory_bytes))
    data = b"".join(bytes(block).ljust(block_size, b"\x00") for block in blocks)
    return header + directory_bytes + padding + data


def merge_dat(base: bytes, addition: bytes) -> bytes:
    base_header = struct.unpack_from("<6I", base)
    add_header = struct.unpack_from("<6I", addition)
    if base_header[:2] != (MAGIC, VERSION) or add_header[:2] != (MAGIC, VERSION):
        raise ValueError("caption database has an unsupported header")
    if base_header[3] != add_header[3]:
        raise ValueError("caption databases use different block sizes")

    base_blocks, block_size, base_count, base_data_offset = (
        base_header[2], base_header[3], base_header[4], base_header[5]
    )
    add_blocks, add_count, add_data_offset = add_header[2], add_header[4], add_header[5]
    base_directory = [struct.unpack_from("<IIHH", base, 24 + index * 12) for index in range(base_count)]
    add_directory = [struct.unpack_from("<IIHH", addition, 24 + index * 12) for index in range(add_count)]
    base_hashes = {entry[0] for entry in base_directory}
    duplicate_hashes = base_hashes & {entry[0] for entry in add_directory}
    if duplicate_hashes:
        raise ValueError(f"base database already contains {len(duplicate_hashes)} added caption hashes")
    adjusted_addition = [
        (hash_value, block_number + base_blocks, offset, length)
        for hash_value, block_number, offset, length in add_directory
    ]
    directory = base_directory + adjusted_addition
    directory_end = 24 + len(directory) * 12
    data_offset = (directory_end + DIRECTORY_ALIGNMENT - 1) // DIRECTORY_ALIGNMENT * DIRECTORY_ALIGNMENT
    header = struct.pack(
        "<6I", MAGIC, VERSION, base_blocks + add_blocks, block_size, len(directory), data_offset
    )
    directory_bytes = b"".join(struct.pack("<IIHH", *entry) for entry in directory)
    padding = bytes(data_offset - len(header) - len(directory_bytes))
    base_data = base[base_data_offset:base_data_offset + base_blocks * block_size]
    add_data = addition[add_data_offset:add_data_offset + add_blocks * block_size]
    return header + directory_bytes + padding + base_data + add_data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    parser.add_argument("--base-txt", type=Path)
    parser.add_argument("--base-dat", type=Path)
    parser.add_argument("--basename", default="subtitles_english")
    parser.add_argument("--prepend-txt", type=Path, action="append", default=[])
    parser.add_argument(
        "--omit-event",
        action="append",
        default=[],
        help="omit a caption token (repeatable; matching is case-insensitive)",
    )
    args = parser.parse_args()

    if bool(args.base_txt) != bool(args.base_dat):
        parser.error("--base-txt and --base-dat must be used together")

    entries, collisions, omitted = load_entries(args.source, set(args.omit_event))
    if args.prepend_txt:
        entries = unique_entries([*(read_txt_entries(path) for path in args.prepend_txt), entries])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = args.output_dir / f"{args.basename}.txt"
    dat_path = args.output_dir / f"{args.basename}.dat"
    addition = build_dat(entries, args.block_size)
    if args.base_txt:
        write_merged_txt(txt_path, args.base_txt, entries)
        dat_path.write_bytes(merge_dat(args.base_dat.read_bytes(), addition))
    else:
        write_txt(txt_path, entries)
        dat_path.write_bytes(addition)

    print(f"Wrote {len(entries)} caption tokens")
    print(f"TXT: {txt_path}")
    print(f"DAT: {dat_path}")
    print(f"Omitted empty rows: {omitted}")
    if collisions:
        print("Random-wave aliases using their first transcript for this trial:")
        for event, extras in collisions.items():
            print(f"  {event}: ignored {len(extras)} additional rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
