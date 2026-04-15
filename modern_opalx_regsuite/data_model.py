from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Iterable, List, Optional

from pydantic import BaseModel, AfterValidator, ConfigDict, Field


def _ensure_utc(v: datetime) -> datetime:
    """Coerce a naive datetime to UTC so aware/naive comparisons never raise."""
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


# Use this instead of bare `datetime` for any timestamp field that may be
# serialised/deserialised from JSON files written before timezone support.
# AfterValidator runs once Pydantic has already parsed the string → datetime.
UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


class UnitTestCase(BaseModel):
    name: str
    status: str  # e.g. "passed", "failed"
    duration_seconds: Optional[float] = None
    output_snippet: Optional[str] = None


class RegressionMetric(BaseModel):
    metric: str
    mode: str
    eps: Optional[float] = None
    delta: Optional[float] = None
    state: str  # "passed" | "failed" | "broken"
    reference_value: Optional[float] = None
    current_value: Optional[float] = None
    plot: Optional[str] = None  # relative path, e.g. "plots/foo.svg"


class RegressionSimulation(BaseModel):
    name: str
    description: Optional[str] = None
    state: Optional[str] = None
    log_file: Optional[str] = None
    metrics: List[RegressionMetric] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    beamline_plot: Optional[str] = None  # relative path, e.g. "plots/AWAGun-1_beamline.svg"
    exit_code: Optional[int] = None
    crash_signal: Optional[str] = None   # e.g. "SIGSEGV" when killed by a signal
    crash_summary: Optional[str] = None  # MPI signal block extracted from the log


class UnitTestsReport(BaseModel):
    tests: List[UnitTestCase] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status.lower() == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.status.lower() == "failed")


class RegressionTestsReport(BaseModel):
    simulations: List[RegressionSimulation] = Field(default_factory=list)

    @property
    def all_metrics(self) -> Iterable[RegressionMetric]:
        for sim in self.simulations:
            for m in sim.metrics:
                yield m

    @property
    def total(self) -> int:
        return sum(1 for _ in self.all_metrics)

    @property
    def passed(self) -> int:
        return sum(1 for m in self.all_metrics if m.state.lower() == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for m in self.all_metrics if m.state.lower() == "failed")

    @property
    def broken(self) -> int:
        return sum(1 for m in self.all_metrics if m.state.lower() == "broken")

    @property
    def crashed(self) -> int:
        return sum(1 for m in self.all_metrics if m.state.lower() == "crashed")


class RunMeta(BaseModel):
    """Per-run metadata stored at ``runs/<branch>/<arch>/<run_id>/run-meta.json``.

    SENSITIVE-DATA RULE: This file lives under ``data_root`` which may be shared
    publicly. **Never** add fields here that hold raw SSH hostnames, usernames,
    file paths, or credentials. The user-chosen ``connection_name`` is the only
    identity surface allowed.
    """

    # Accept legacy keys (execution_host / execution_user) silently when reading
    # historical run-meta.json files written by pre-refactor code, but strip
    # them on the next save by never re-emitting them.
    model_config = ConfigDict(extra="ignore")

    branch: str
    arch: str
    run_id: str
    started_at: UtcDatetime
    finished_at: Optional[UtcDatetime] = None
    status: str = "unknown"  # "running" | "passed" | "failed" | "broken" | "unknown"

    opalx_commit: Optional[str] = None
    tests_repo_commit: Optional[str] = None
    regtest_branch: Optional[str] = None

    # The user-chosen connection name (e.g. "daint", "local"). Safe for public
    # sharing as long as the user did not embed identifying info in the name.
    connection_name: Optional[str] = None

    # The username that triggered the run.
    triggered_by: Optional[str] = None

    unit_tests_total: int = 0
    unit_tests_failed: int = 0

    regression_total: int = 0
    regression_passed: int = 0
    regression_failed: int = 0
    regression_broken: int = 0

    # Soft-delete flag. False for newly written runs and for any historical
    # run-meta.json file that predates this field (default applies). Flipped
    # in-place by the archive service; never moves files on disk.
    archived: bool = False

    # Visibility flag. False = private (default); True = visible on the
    # unauthenticated /api/public/* surface. Flipped via the publish button
    # on the run detail page, or stamped at run creation when a schedule has
    # public=True.
    public: bool = False

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class RunIndexEntry(BaseModel):
    """Index entry for a run. Lives under ``data_root`` — same sensitive-data rule as RunMeta."""

    model_config = ConfigDict(extra="ignore")

    branch: str
    arch: str
    run_id: str
    started_at: UtcDatetime
    finished_at: Optional[UtcDatetime]
    status: str
    connection_name: Optional[str] = None
    triggered_by: Optional[str] = None
    regtest_branch: Optional[str] = None
    unit_tests_total: int = 0
    unit_tests_failed: int = 0
    regression_total: int = 0
    regression_passed: int = 0
    regression_failed: int = 0
    regression_broken: int = 0
    archived: bool = False
    public: bool = False


class BranchIndex(BaseModel):
    branch: str
    architectures: List[str] = Field(default_factory=list)


def run_dir(data_root: Path, branch: str, arch: str, run_id: str) -> Path:
    return data_root / "runs" / branch / arch / run_id


def runs_index_path(data_root: Path, branch: str, arch: str) -> Path:
    return data_root / "runs-index" / branch / f"{arch}.json"


def branches_index_path(data_root: Path) -> Path:
    return data_root / "branches.json"

