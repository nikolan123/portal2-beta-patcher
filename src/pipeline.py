from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from threading import Event
import uuid

from extractor import extract_depot
from models import BuildCancelled, BuildInputs, BuildReport, PatchContext, ProgressEvent, ProgressCallback
from patches import PATCHES
from steam import validate_hl2


BLOB_SHA256 = "3a6ea6546058bfe1a396d5167a869f626e26b9118eee9c95594d08e2b87c169f"
DAT_SHA256 = "ae227e4c03f23bf10cd2dc3032dd5007c699f761aec9acc63989a95787f22276"


def hash_file(path: Path, phase: str, emit: ProgressCallback, cancel: Event) -> str:
    total = path.stat().st_size
    completed = 0
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            if cancel.is_set():
                raise BuildCancelled("Build cancelled")
            digest.update(chunk)
            completed += len(chunk)
            emit(ProgressEvent(phase, completed, max(total, 1), f"Checking {path.name}"))
    return digest.hexdigest()


class BuildPipeline:
    def __init__(self, emit: ProgressCallback, cancel_event: Event):
        self.emit = emit
        self.cancel_event = cancel_event

    def run(self, inputs: BuildInputs) -> Path:
        blob = inputs.blob_path.expanduser().resolve()
        dat = inputs.dat_path.expanduser().resolve()
        hl2 = validate_hl2(inputs.hl2_path)
        output = inputs.output_path.expanduser().resolve()
        if not blob.is_file() or not dat.is_file():
            raise FileNotFoundError("The selected BLOB or DAT does not exist")
        if output.exists():
            raise FileExistsError(f"Output already exists: {output}")

        report = BuildReport()
        blob_hash = hash_file(blob, "validate", self.emit, self.cancel_event)
        dat_hash = hash_file(dat, "validate", self.emit, self.cancel_event)
        report.input_hashes = {"blob": blob_hash, "dat": dat_hash}
        if blob_hash != BLOB_SHA256:
            raise RuntimeError(f"This is not the expected 852_0 BLOB ({blob_hash})")
        if dat_hash != DAT_SHA256:
            raise RuntimeError(f"This is not the expected 852_0 DAT ({dat_hash})")

        staging = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex[:8]}")
        try:
            report.extraction = extract_depot(blob, dat, staging, self.emit, self.cancel_event)
            context = PatchContext(staging, hl2, report, self.cancel_event)
            for index, patch in enumerate(PATCHES, start=1):
                if self.cancel_event.is_set():
                    raise BuildCancelled("Build cancelled")
                self.emit(ProgressEvent("patches", index - 1, len(PATCHES), f"{patch.id}: {patch.display_name}"))
                needed = patch.check(context)
                if needed:
                    patch.apply(context, self.emit)
                patch.verify(context)
                report.patches.append(
                    {"id": patch.id, "name": patch.display_name, "status": "applied" if needed else "already_applied"}
                )
                self.emit(ProgressEvent("patches", index, len(PATCHES), f"Finished {patch.id}"))

            report_data = asdict(report)
            report_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            report_data["output"] = str(output)
            (staging / "patcher-report.json").write_text(
                json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            staging.replace(output)
            self.emit(ProgressEvent("complete", 1, 1, "Build ready"))
            return output
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise


def configure_logging() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    base = local_app_data / "Portal2BetaPatcher" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"patcher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    return path
