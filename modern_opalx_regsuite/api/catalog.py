from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from ..catalog import CatalogReport, list_catalog_tests
from ..config import SuiteConfig
from ..flakiness import compute_flakiness, latest_simulation_statuses
from .deps import get_config, require_auth


router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/tests", response_model=CatalogReport)
def catalog_tests(
    _user: Annotated[str, Depends(require_auth)],
    cfg: SuiteConfig = Depends(get_config),
    branch: str = Query("master", description="regression-tests-x branch"),
    include_disabled: bool = Query(True),
    opalx_branch: Optional[str] = Query(None),
    arch: Optional[str] = Query(None),
) -> CatalogReport:
    last_status_by_name: dict[str, str] | None = None
    flaky_names: set[str] | None = None
    if opalx_branch and arch:
        last_status_by_name = latest_simulation_statuses(
            cfg.resolved_data_root,
            opalx_branch,
            arch,
            branch,
        )
        flaky_report = compute_flakiness(
            cfg.resolved_data_root,
            opalx_branch,
            arch,
            branch,
        )
        flaky_names = {sim.name for sim in flaky_report.simulations}
    return list_catalog_tests(
        cfg.resolved_regtests_repo_root,
        branch,
        include_disabled=include_disabled,
        last_status_by_name=last_status_by_name,
        flaky_names=flaky_names,
    )
