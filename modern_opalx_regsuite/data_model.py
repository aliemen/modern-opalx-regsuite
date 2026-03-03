from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field


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
    metrics: List[RegressionMetric] = Field(default_factory=list)


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


class RunMeta(BaseModel):
    branch: str
    arch: str
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str = "unknown"  # "running" | "passed" | "failed" | "broken" | "unknown"

    opalx_commit: Optional[str] = None
    tests_repo_commit: Optional[str] = None

    unit_tests_total: int = 0
    unit_tests_failed: int = 0

    regression_total: int = 0
    regression_failed: int = 0
    regression_broken: int = 0

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class RunIndexEntry(BaseModel):
    branch: str
    arch: str
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    unit_tests_failed: int
    regression_failed: int
    regression_broken: int


class BranchIndex(BaseModel):
    branch: str
    architectures: List[str] = Field(default_factory=list)


def run_dir(data_root: Path, branch: str, arch: str, run_id: str) -> Path:
    return data_root / "runs" / branch / arch / run_id


def runs_index_path(data_root: Path, branch: str, arch: str) -> Path:
    return data_root / "runs-index" / branch / f"{arch}.json"


def branches_index_path(data_root: Path) -> Path:
    return data_root / "branches.json"

