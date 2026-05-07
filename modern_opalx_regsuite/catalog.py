from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class CatalogMetricCheck(BaseModel):
    metric: str
    mode: str
    eps: Optional[float] = None


class CatalogTestEntry(BaseModel):
    name: str
    enabled: bool
    path: str
    description: Optional[str] = None
    metrics: list[CatalogMetricCheck] = Field(default_factory=list)
    has_input: bool = False
    has_local: bool = False
    reference_stat_count: int = 0
    multi_container_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_status: Optional[str] = None
    last_run_id: Optional[str] = None
    flaky: bool = False


class CatalogReport(BaseModel):
    branch: str
    commit: Optional[str] = None
    commit_url: Optional[str] = None
    tests: list[CatalogTestEntry] = Field(default_factory=list)


def _git(
    repo: Path,
    args: list[str],
    *,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def resolve_git_ref(repo: Path, branch: str) -> Optional[str]:
    for candidate in (branch, f"origin/{branch}"):
        result = _git(repo, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
        if result.returncode == 0 and result.stdout.strip():
            return candidate
    return None


def _list_tree(repo: Path, ref: str) -> list[str]:
    result = _git(
        repo,
        ["ls-tree", "-r", "--name-only", ref, "RegressionTests", "disabledTests"],
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _show_text(repo: Path, ref: str, path: str) -> Optional[str]:
    result = _git(repo, ["show", f"{ref}:{path}"], timeout=5)
    if result.returncode != 0:
        return None
    return result.stdout


def _repo_remote_url(repo: Path) -> Optional[str]:
    result = _git(repo, ["remote", "get-url", "origin"], timeout=5)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def github_commit_url(repo_url: Optional[str], commit: Optional[str]) -> Optional[str]:
    if not repo_url or not commit:
        return None
    url = repo_url.strip()
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:") :]
    elif url.startswith("ssh://git@github.com/"):
        url = "https://github.com/" + url[len("ssh://git@github.com/") :]
    if url.endswith(".git"):
        url = url[:-4]
    if not url.startswith("https://github.com/"):
        return None
    return f"{url}/commit/{commit}"


def _parse_rt_text(text: Optional[str]) -> tuple[Optional[str], list[CatalogMetricCheck]]:
    if not text:
        return None, []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    description = lines[0].strip().strip('"') if lines else None
    metrics: list[CatalogMetricCheck] = []
    for line in lines[1:]:
        if not line.startswith("stat"):
            continue
        m = re.match(r'^stat\s+"([^"]+)"\s+(\S+)\s+(\S+)\s*$', line)
        if not m:
            continue
        eps: Optional[float]
        try:
            eps = float(m.group(3))
        except ValueError:
            eps = None
        metrics.append(
            CatalogMetricCheck(metric=m.group(1), mode=m.group(2), eps=eps)
        )
    return description, metrics


_CONTAINER_STAT_RE = re.compile(r"_c(\d+)\.stat$")


def list_catalog_tests(
    repo: Path,
    branch: str,
    *,
    include_disabled: bool = True,
    last_status_by_name: Optional[dict[str, str]] = None,
    last_run_by_name: Optional[dict[str, str]] = None,
    flaky_names: Optional[set[str]] = None,
    repo_url: Optional[str] = None,
) -> CatalogReport:
    ref = resolve_git_ref(repo, branch)
    if ref is None:
        return CatalogReport(branch=branch, tests=[])

    commit_result = _git(repo, ["rev-parse", ref])
    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    commit_url = github_commit_url(repo_url or _repo_remote_url(repo), commit)
    paths = _list_tree(repo, ref)
    roots: dict[str, list[str]] = {}
    for path in paths:
        parts = path.split("/")
        if len(parts) < 2:
            continue
        top, name = parts[0], parts[1]
        if top not in {"RegressionTests", "disabledTests"}:
            continue
        if top == "disabledTests" and not include_disabled:
            continue
        roots.setdefault(f"{top}/{name}", []).append(path)

    out: list[CatalogTestEntry] = []
    for root, files in sorted(roots.items(), key=lambda item: item[0].lower()):
        top, name = root.split("/", 1)
        enabled = top == "RegressionTests"
        file_names = {Path(path).name for path in files}
        rel_files = [path[len(root) + 1 :] for path in files if path.startswith(root + "/")]
        has_input = f"{name}.in" in file_names
        has_local = f"{name}.local" in file_names
        rt_path = f"{root}/{name}.rt"
        description, metrics = _parse_rt_text(_show_text(repo, ref, rt_path))
        reference_stats = [
            f for f in rel_files
            if f.startswith("reference/") and f.endswith(".stat")
        ]
        multi_refs = sorted(
            Path(f).name for f in reference_stats if _CONTAINER_STAT_RE.search(f)
        )

        warnings: list[str] = []
        if not has_input:
            warnings.append("missing .in file")
        if f"{name}.rt" not in file_names:
            warnings.append("missing .rt file")
        if not reference_stats:
            warnings.append("missing reference .stat file")
        if enabled and not has_local:
            warnings.append("missing .local runner")

        out.append(
            CatalogTestEntry(
                name=name,
                enabled=enabled,
                path=root,
                description=description,
                metrics=metrics,
                has_input=has_input,
                has_local=has_local,
                reference_stat_count=len(reference_stats),
                multi_container_refs=multi_refs,
                warnings=warnings,
                last_status=(last_status_by_name or {}).get(name),
                last_run_id=(last_run_by_name or {}).get(name),
                flaky=name in (flaky_names or set()),
            )
        )

    return CatalogReport(branch=branch, commit=commit, commit_url=commit_url, tests=out)
