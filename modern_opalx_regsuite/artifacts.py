from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .data_model import RegressionTestsReport, RunMeta, UnitTestsReport


MANIFEST_NAME = "artifact-manifest.json"
MANIFEST_SCHEMA_VERSION = 1


ArtifactKind = Literal[
    "meta",
    "unit-report",
    "regression-report",
    "log",
    "plot",
    "beamline",
    "manifest",
    "other",
]


class RunArtifactFile(BaseModel):
    path: str
    kind: ArtifactKind
    size_bytes: int
    sha256: str


class RunArtifactManifest(BaseModel):
    schema_version: int = MANIFEST_SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    files: list[RunArtifactFile] = Field(default_factory=list)


class IntegrityIssue(BaseModel):
    severity: Literal["warning", "error"]
    code: str
    message: str
    path: Optional[str] = None


class RunIntegrityReport(BaseModel):
    status: Literal["ok", "warning", "error"]
    issues: list[IntegrityIssue] = Field(default_factory=list)
    manifest: Optional[RunArtifactManifest] = None


def _rel(path: Path, run_root: Path) -> str:
    return path.relative_to(run_root).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kind_for(rel_path: str) -> ArtifactKind:
    if rel_path == "run-meta.json":
        return "meta"
    if rel_path == "unit-tests.json":
        return "unit-report"
    if rel_path == "regression-tests.json":
        return "regression-report"
    if rel_path == MANIFEST_NAME:
        return "manifest"
    if rel_path.startswith("logs/"):
        return "log"
    if rel_path.startswith("plots/") and rel_path.endswith(".svg"):
        return "plot"
    if rel_path.startswith("plots/") and rel_path.endswith(".json"):
        return "beamline"
    return "other"


def _iter_manifest_files(run_root: Path) -> list[Path]:
    out: list[Path] = []
    if not run_root.is_dir():
        return out
    for path in sorted(run_root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(run_root).parts
        if rel_parts[0] == "work":
            continue
        if path.name == MANIFEST_NAME:
            continue
        out.append(path)
    return out


def build_artifact_manifest(run_root: Path) -> RunArtifactManifest:
    files = [
        RunArtifactFile(
            path=_rel(path, run_root),
            kind=_kind_for(_rel(path, run_root)),
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
        )
        for path in _iter_manifest_files(run_root)
    ]
    return RunArtifactManifest(files=files)


def write_artifact_manifest(run_root: Path) -> RunArtifactManifest:
    manifest = build_artifact_manifest(run_root)
    target = run_root / MANIFEST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(mode="json"), f, indent=2, default=str)
    return manifest


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _safe_rel_path(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        return None
    return p.as_posix()


def _referenced_artifacts(regression: RegressionTestsReport) -> set[str]:
    refs: set[str] = set()
    for sim in regression.simulations:
        for raw in (sim.log_file, sim.beamline_plot, sim.beamline_3d_data):
            rel = _safe_rel_path(raw)
            if rel:
                refs.add(rel)
        for container in sim.containers:
            for metric in container.metrics:
                rel = _safe_rel_path(metric.plot)
                if rel:
                    refs.add(rel)
    return refs


def check_run_integrity(run_root: Path) -> RunIntegrityReport:
    issues: list[IntegrityIssue] = []

    def issue(
        severity: Literal["warning", "error"],
        code: str,
        message: str,
        path: Optional[str] = None,
    ) -> None:
        issues.append(
            IntegrityIssue(
                severity=severity,
                code=code,
                message=message,
                path=path,
            )
        )

    if not run_root.is_dir():
        issue("error", "run-dir-missing", "Run directory is missing.")
        return RunIntegrityReport(status="error", issues=issues)

    manifest: Optional[RunArtifactManifest] = None
    manifest_path = run_root / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            manifest = RunArtifactManifest.model_validate(_load_json(manifest_path))
        except Exception as exc:
            issue(
                "error",
                "manifest-invalid",
                f"artifact-manifest.json is not valid: {exc}",
                MANIFEST_NAME,
            )
    else:
        issue(
            "warning",
            "manifest-missing",
            "artifact-manifest.json has not been generated for this run.",
            MANIFEST_NAME,
        )

    required = [
        "run-meta.json",
        "unit-tests.json",
        "regression-tests.json",
        "logs/pipeline.log",
    ]
    for rel in required:
        if not (run_root / rel).is_file():
            issue("error", "required-file-missing", "Required artifact is missing.", rel)

    meta: Optional[RunMeta] = None
    unit: Optional[UnitTestsReport] = None
    regression: Optional[RegressionTestsReport] = None
    validators = [
        ("run-meta.json", RunMeta),
        ("unit-tests.json", UnitTestsReport),
        ("regression-tests.json", RegressionTestsReport),
    ]
    for rel, model in validators:
        path = run_root / rel
        if not path.is_file():
            continue
        try:
            parsed = model.model_validate(_load_json(path))
            if rel == "run-meta.json":
                meta = parsed
            elif rel == "unit-tests.json":
                unit = parsed
            else:
                regression = parsed
        except Exception as exc:
            issue("error", "json-invalid", f"{rel} is not valid: {exc}", rel)

    del meta, unit
    if regression is not None:
        for rel in sorted(_referenced_artifacts(regression)):
            if not (run_root / rel).is_file():
                issue(
                    "error",
                    "referenced-artifact-missing",
                    "A report references this artifact, but it is missing.",
                    rel,
                )

    if manifest is not None:
        manifest_by_path = {f.path: f for f in manifest.files}
        for entry in manifest.files:
            rel_path = Path(entry.path)
            path = run_root / rel_path
            if rel_path.is_absolute() or ".." in rel_path.parts:
                issue(
                    "error",
                    "manifest-path-unsafe",
                    "Manifest contains an unsafe path.",
                    entry.path,
                )
                continue
            if not path.is_file():
                issue(
                    "error",
                    "manifest-file-missing",
                    "Manifest entry is missing on disk.",
                    entry.path,
                )
                continue
            stat = path.stat()
            if stat.st_size != entry.size_bytes:
                issue(
                    "error",
                    "manifest-size-mismatch",
                    "Manifest size does not match the file on disk.",
                    entry.path,
                )
            elif _sha256(path) != entry.sha256:
                issue(
                    "error",
                    "manifest-hash-mismatch",
                    "Manifest hash does not match the file on disk.",
                    entry.path,
                )

        for path in _iter_manifest_files(run_root):
            rel = _rel(path, run_root)
            if rel not in manifest_by_path:
                issue(
                    "warning",
                    "manifest-entry-missing",
                    "File exists on disk but is not recorded in the manifest.",
                    rel,
                )

    status: Literal["ok", "warning", "error"] = "ok"
    if any(i.severity == "error" for i in issues):
        status = "error"
    elif issues:
        status = "warning"
    return RunIntegrityReport(status=status, issues=issues, manifest=manifest)
