"""
Patch 2: Mount the beta's required content folders and optional HL2 assets
"""
from __future__ import annotations

import re

from models import PatchContext, ProgressCallback
from patches.base import atomic_write, backup_file


SEARCH_BLOCK = re.compile(r"(SearchPaths\s*\{)(.*?)(\n\s*\})", re.IGNORECASE | re.DOTALL)


class SearchPathsPatch:
    id = "p2"
    display_name = "Game search paths"
    description = "Make the beta mount its temp content and platform files, plus Half-Life 2 when selected."

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "GameInfo.txt"

    def check(self, context: PatchContext) -> bool:
        text = self._path(context).read_text(encoding="utf-8", errors="replace").casefold()
        tempcontent = re.search(r"\bgame\s+portal2_tempcontent\b", text)
        platform = "|gameinfo_path|..\\platform" in text
        hl2 = re.search(r"\bgame\s+hl2\b", text)
        return (
            not platform
            or tempcontent is None
            or (context.hl2_source is not None and hl2 is None)
            or (hl2 is not None and tempcontent.start() > hl2.start())
        )

    def apply(self, context: PatchContext, progress: ProgressCallback) -> None:
        path = self._path(context)
        backup_file(path, "GameInfo.original.bak", context)
        text = path.read_text(encoding="utf-8", errors="strict")
        match = SEARCH_BLOCK.search(text)
        if not match:
            raise RuntimeError("GameInfo.txt has no SearchPaths block")
        body = match.group(2)
        lines = body.splitlines()
        content = [line for line in lines if line.strip()]
        content = [
            line
            for line in content
            if "|gameinfo_path|..\\platform" not in line.casefold()
            and not re.search(r"\bgame\s+portal2_tempcontent\b", line, re.IGNORECASE)
        ]
        insert_at = next(
            (index + 1 for index, line in enumerate(content) if "|gameinfo_path|." in line.casefold()),
            0,
        )
        content[insert_at:insert_at] = [
            "\t\t\tGame\t\t\t\tportal2_tempcontent",
            "\t\t\tGame\t\t\t\t|gameinfo_path|..\\platform",
        ]
        if context.hl2_source is not None and not any(
            re.search(r"\bgame\s+hl2\b", line, re.IGNORECASE) for line in content
        ):
            content.append("\t\t\tGame\t\t\t\thl2")
        replacement = match.group(1) + "\n" + "\n".join(content) + match.group(3)
        atomic_write(path, (text[: match.start()] + replacement + text[match.end() :]).encode("utf-8"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Required game search paths are still missing")
