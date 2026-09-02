"""
Patch 2: Edit GameInfo.txt so the beta can find its platform and hl2 folders
"""
from __future__ import annotations

import re

from models import PatchContext, ProgressCallback
from patches.base import atomic_write, backup_file


SEARCH_BLOCK = re.compile(r"(SearchPaths\s*\{)(.*?)(\n\s*\})", re.IGNORECASE | re.DOTALL)


class SearchPathsPatch:
    id = "p2"
    display_name = "Game search paths"

    def _path(self, context: PatchContext):
        return context.root / "portal2" / "GameInfo.txt"

    def check(self, context: PatchContext) -> bool:
        text = self._path(context).read_text(encoding="utf-8", errors="replace").casefold()
        tempcontent = re.search(r"\bgame\s+portal2_tempcontent\b", text)
        hl2 = re.search(r"\bgame\s+hl2\b", text)
        return (
            "|gameinfo_path|..\\platform" not in text
            or tempcontent is None
            or hl2 is None
            or tempcontent.start() > hl2.start()
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
        if not any("|gameinfo_path|..\\platform" in line.casefold() for line in content):
            content.insert(1 if content else 0, "\t\t\tGame\t\t\t\t|gameinfo_path|..\\platform")
        if not any(re.search(r"\bgame\s+hl2\b", line, re.IGNORECASE) for line in content):
            content.append("\t\t\tGame\t\t\t\thl2")
        tempcontent_index = next(
            (index for index, line in enumerate(content) if re.search(r"\bgame\s+portal2_tempcontent\b", line, re.IGNORECASE)),
            None,
        )
        tempcontent_line = (
            content.pop(tempcontent_index)
            if tempcontent_index is not None
            else "\t\t\tGame\t\t\t\tportal2_tempcontent"
        )
        hl2_index = next(
            index
            for index, line in enumerate(content)
            if re.search(r"\bgame\s+hl2\b", line, re.IGNORECASE)
        )
        content.insert(hl2_index, tempcontent_line)
        replacement = match.group(1) + "\n" + "\n".join(content) + match.group(3)
        atomic_write(path, (text[: match.start()] + replacement + text[match.end() :]).encode("utf-8"))

    def verify(self, context: PatchContext) -> None:
        if self.check(context):
            raise RuntimeError("Required game search paths are still missing")
