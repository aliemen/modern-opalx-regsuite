from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..archive_service import locked_index
from ..artifacts import write_artifact_manifest
from ..data_model import (
    RunIndexEntry,
    RunMeta,
    branches_index_path,
    runs_index_path,
)
from .execution import RunPaths, _append_pipeline_line, _write_json


def _cancel_run(meta: RunMeta, paths: RunPaths, data_root: Path) -> RunMeta:
    """Finalise a cancelled run and persist it."""
    _append_pipeline_line(paths.pipeline_log_path, "== PHASE: done status=cancelled ==")
    meta.status = "cancelled"
    meta.finished_at = datetime.now(timezone.utc)
    _write_json(paths.meta_path, meta.model_dump())
    write_artifact_manifest(paths.root)
    _update_indexes(data_root, meta)
    return meta


def _update_indexes(data_root: Path, meta: RunMeta) -> None:
    index_path = runs_index_path(data_root, meta.branch, meta.arch)
    with locked_index(index_path):
        entries: list[RunIndexEntry] = []
        if index_path.is_file():
            with index_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            entries = [RunIndexEntry.model_validate(e) for e in raw]

        entries.append(
            RunIndexEntry(
                branch=meta.branch,
                arch=meta.arch,
                run_id=meta.run_id,
                started_at=meta.started_at,
                finished_at=meta.finished_at,
                status=meta.status,
                connection_name=meta.connection_name,
                triggered_by=meta.triggered_by,
                regtest_branch=meta.regtest_branch,
                unit_tests_total=meta.unit_tests_total,
                unit_tests_failed=meta.unit_tests_failed,
                regression_total=meta.regression_total,
                regression_passed=meta.regression_passed,
                regression_failed=meta.regression_failed,
                regression_broken=meta.regression_broken,
                archived=meta.archived,
                public=meta.public,
                run_options=meta.run_options,
                rerun_of=meta.rerun_of,
            )
        )
        entries.sort(key=lambda e: e.started_at, reverse=True)
        _write_json(index_path, [e.model_dump() for e in entries])

    branches_path = branches_index_path(data_root)
    branches: dict[str, list[str]] = {}
    if branches_path.is_file():
        with branches_path.open("r", encoding="utf-8") as f:
            branches = json.load(f)
    archs = set(branches.get(meta.branch, []))
    archs.add(meta.arch)
    branches[meta.branch] = sorted(archs)
    _write_json(branches_path, branches)
