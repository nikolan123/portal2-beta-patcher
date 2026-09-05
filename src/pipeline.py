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

from extractor import extract_depot, extract_revision_chain
from models import BuildCancelled, BuildInputs, BuildReport, PatchContext, ProgressEvent, ProgressCallback
from patches import PATCHES, normalize_patch_ids
from steam import validate_hl2, validate_portal_2


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
        if inputs.mode not in {"852_0", "generic"}:
            raise ValueError(f"Unknown extraction mode: {inputs.mode}")
        blob = inputs.blob_path.expanduser().resolve()
        dat = inputs.dat_path.expanduser().resolve()
        output = inputs.output_path.expanduser().resolve()
        requested_ids = (
            tuple(patch.id for patch in PATCHES)
            if inputs.selected_patch_ids is None
            else inputs.selected_patch_ids
        )
        known_ids = {patch.id for patch in PATCHES}
        unknown_ids = set(requested_ids) - known_ids
        if unknown_ids:
            raise ValueError(f"Unknown patch IDs: {', '.join(sorted(unknown_ids))}")
        selected_ids = set(normalize_patch_ids(
            requested_ids,
            inputs.mode,
            runnable=inputs.mode == "852_0",
            depot_id=inputs.depot_id,
            depot_version=inputs.depot_version,
        ))
        if "p10" in selected_ids:
            if inputs.goldberg_archive_path is None:
                raise ValueError("Select the Goldberg ZIP to use")
            goldberg_archive = inputs.goldberg_archive_path.expanduser().resolve()
            if not goldberg_archive.is_file():
                raise FileNotFoundError(f"Goldberg ZIP does not exist: {goldberg_archive}")
        else:
            goldberg_archive = None
        needs_hl2 = bool(selected_ids & {"p1", "p3"})
        if needs_hl2 and inputs.hl2_path is None:
            raise ValueError("Half-Life 2 is required for the HL2 content support fix")
        hl2 = validate_hl2(inputs.hl2_path) if needs_hl2 else None
        needs_hammer = "p7" in selected_ids
        if needs_hammer and inputs.portal2_path is None:
            raise ValueError("A retail Portal 2 installation is required for the Hammer and HLMV fix")
        portal2 = validate_portal_2(inputs.portal2_path) if needs_hammer else None
        source_files = [(blob, dat)] if inputs.mode == "852_0" else [
            (item.blob_path.expanduser().resolve(), item.dat_path.expanduser().resolve())
            for item in inputs.revision_chain
        ]
        if not source_files or any(not left.is_file() or not right.is_file() for left, right in source_files):
            raise FileNotFoundError("A selected BLOB or DAT does not exist")
        if output.exists():
            raise FileExistsError(f"Output already exists: {output}")

        report = BuildReport()
        if inputs.mode == "852_0" and hl2 is None:
            report.warnings.append("Half-Life 2 content support was not installed")
        if inputs.mode == "852_0":
            blob_hash = hash_file(blob, "validate", self.emit, self.cancel_event)
            dat_hash = hash_file(dat, "validate", self.emit, self.cancel_event)
            report.input_hashes = {"blob": blob_hash, "dat": dat_hash}
            if blob_hash != BLOB_SHA256:
                raise RuntimeError(f"This is not the expected 852_0 BLOB ({blob_hash})")
            if dat_hash != DAT_SHA256:
                raise RuntimeError(f"This is not the expected 852_0 DAT ({dat_hash})")
        else:
            final_revision = inputs.revision_chain[-1]
            if inputs.depot_id is not None and inputs.depot_id != final_revision.depot_id:
                raise ValueError("Selected depot ID does not match the resolved revision chain")
            if inputs.depot_version is not None and inputs.depot_version != final_revision.version:
                raise ValueError("Selected depot version does not match the resolved revision chain")
            if inputs.depot_crc is not None and inputs.depot_crc != final_revision.crc:
                raise ValueError("Selected depot CRC does not match the resolved revision chain")
            if inputs.custom_depot_key is not None and len(inputs.custom_depot_key) != 16:
                raise ValueError("A custom depot key must be exactly 16 bytes")
            hashes: dict[str, str] = {}
            for revision, (revision_blob, revision_dat) in zip(inputs.revision_chain, source_files, strict=True):
                blob_hash = hash_file(revision_blob, "validate", self.emit, self.cancel_event)
                dat_hash = hash_file(revision_dat, "validate", self.emit, self.cancel_event)
                if revision.blob_sha256 and blob_hash != revision.blob_sha256:
                    raise RuntimeError(f"BLOB SHA-256 mismatch: {revision_blob.name}")
                if revision.dat_sha256 and dat_hash != revision.dat_sha256:
                    raise RuntimeError(f"DAT SHA-256 mismatch: {revision_dat.name}")
                hashes[f"{revision.version}:blob"] = blob_hash
                hashes[f"{revision.version}:dat"] = dat_hash
            report.input_hashes = hashes

        staging = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex[:8]}")
        try:
            if inputs.mode == "852_0":
                report.extraction = extract_depot(blob, dat, staging, self.emit, self.cancel_event)
            else:
                report.extraction = extract_revision_chain(
                    inputs.revision_chain,
                    staging,
                    self.emit,
                    self.cancel_event,
                    inputs.custom_depot_key,
                )
                runnable = (staging / "hl2.exe").is_file() and (staging / "portal2" / "GameInfo.txt").is_file()
                if runnable:
                    selected_ids = set(normalize_patch_ids(
                        requested_ids,
                        "generic",
                        runnable=True,
                        depot_id=final_revision.depot_id,
                        depot_version=final_revision.version,
                    ))
                else:
                    selected_ids.clear()
                    report.warnings.append("This depot is content-only and is not independently runnable")
            context = PatchContext(
                staging,
                hl2,
                report,
                self.cancel_event,
                portal2,
                output,
                goldberg_archive,
                mode=inputs.mode,
                supplemental_revision_chains=inputs.supplemental_revision_chains,
            )
            selected_patches = [patch for patch in PATCHES if patch.id in selected_ids]
            for index, patch in enumerate(selected_patches, start=1):
                if self.cancel_event.is_set():
                    raise BuildCancelled("Build cancelled")
                self.emit(ProgressEvent("patches", index - 1, max(len(selected_patches), 1), f"{patch.id}: {patch.display_name}"))
                needed = patch.check(context)
                if needed:
                    patch.apply(context, self.emit)
                patch.verify(context)
                report.patches.append(
                    {"id": patch.id, "name": patch.display_name, "status": "applied" if needed else "already_applied"}
                )
                self.emit(ProgressEvent("patches", index, max(len(selected_patches), 1), f"Finished {patch.id}"))

            report_data = asdict(report)
            report_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            report_data["output"] = str(output)
            metadata = staging / ".p2patcher"
            metadata.mkdir(parents=True, exist_ok=True)
            (metadata / "patcher-report.json").write_text(
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
