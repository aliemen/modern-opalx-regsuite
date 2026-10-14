# Test Skip Config - Design

Date: 2026-10-14
Status: approved design, awaiting spec review

## Goal

Some OPALX unit and regression tests take an unreasonable share of run time. In
run `581-add-3ddynamic-fieldmap/cuda-daint/20261013-131203` (35 min total, about
14 min of test time) three tests account for about 443 s:

| Test | Kind | Duration |
|---|---|---|
| `DBA-COF-Gauss` | regression | 289 s |
| `DBA-COF-Track-1` | regression | 108 s |
| `TestOrbitThreader` | unit (ctest) | 46 s |

Users can define named **test skip configs** and pick one when starting a manual
run. The run skips the listed tests, shows them as `skipped` while running and in
every result view, and records exactly what was skipped so later edits to a
config never rewrite history.

## Decisions

- Skip configs are **global** (shared by all users, like the public execution
  presets). There is no per-architecture list; users create several configs
  (e.g. "Skip slow CPU tests") and pick the one that fits the architecture.
- A config is selected **only on Start Run**. The default is "None (run all
  tests)". **Schedules always run the full suite**; they get no selector.
- Tests are chosen from a **checklist of exact names**, no patterns.
- Skips **never change the run status**. A run with skips can be `passed`.
- Configs are stored in their **own file**, not inside `ExecutionSettings`, so
  Public Settings "reset from config" and its whole-document PUT cannot touch them.
- Skipped tests are written as **placeholder entries** into the existing reports,
  so every view shows them without joining extra data.
- The selected config is **snapshotted at trigger time** into `RunOptions`.

## Data Model

### Config store

File: `users_root/_public/test-skip-configs.json` (atomic write, guarded by
`profiles_lock("_public-test-skips")`).

```python
class TestSkipConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                      # slug, validated with _validate_id
    name: str                    # display name, 1-80 chars
    description: Optional[str] = None
    unit_tests: list[str] = []   # ctest test names
    regression_tests: list[str] = []  # regression test directory names

class TestSkipConfigsDocument(BaseModel):
    version: int = 1
    configs: list[TestSkipConfig] = []
```

Test names must match `^[A-Za-z0-9_.+-]+$`, are stripped, de-duplicated, and
sorted on save. Config ids are unique. The content is public-safe (test names
only), so the snapshot may live under `data_root`.

New module `modern_opalx_regsuite/test_skips.py` holds the models, load/save,
CRUD helpers, `snapshot_for(config_id)`, and the ctest exclude builder.

### Run data

- `RunOptions.skip_config: Optional[SkipConfigSnapshot] = None` where
  `SkipConfigSnapshot {id, name, unit_tests, regression_tests}`. It is persisted in
  `run-meta.json` and the runs index, like the other run options.
- `RunMeta` and `RunIndexEntry` gain `unit_tests_skipped: int = 0` and
  `regression_skipped: int = 0` (count of skipped simulations). Old files stay
  valid through the defaults.
- `UnitTestCase.status` may be `"skipped"`; `UnitTestsReport` gains a `skipped`
  property. `unit_tests_total` keeps counting executed tests only.
- `RegressionSimulation.state` may be `"skipped"` with `containers=[]`.
  Skipped simulations have no metrics, so `regression_total/passed/failed/broken`
  stay correct without changes.

## Backend Flow

1. **Trigger** (`api/runs.py`): `TriggerRequest.skip_config_id: Optional[str]`.
   The handler resolves it with `snapshot_for`; an unknown id returns 422. The
   snapshot is threaded through `runs_core` -> coordinator queue entry ->
   `run_pipeline(skip_config=...)` and stored in `meta.run_options.skip_config`.
   `scheduler/task.py` never sets it.
2. **Regression phase** (`runner/regression_runner.py`, local and remote): after
   discovery, the runner splits the discovered list into `run` and `skip`. For
   each skipped test, in discovery order, it logs `[regression] SKIP <name>` and
   appends `RegressionSimulation(name=..., state="skipped")`. A config name not
   present on that branch produces one pipeline line
   `[regression] Skip config lists <name>, not present on this branch.` and no
   placeholder. `regression-tests.log` gets `<name>: skipped`.
3. **Unit phase** (`runner/pipeline.py`): if the unit command's first token is
   `ctest`, append `-E <regex>` with `regex = ^(A|B|...)$`. Each name is escaped
   for CMake regex syntax (`. + ^ $ * ? ( ) [ ] { } | \`), then the whole regex is
   passed through `shlex.quote`, so it also works inside the remote Slurm `srun`
   step. After `_parse_unit_output`, append `UnitTestCase(status="skipped")` for
   each configured name. If the command is not ctest, log
   `[unit] WARNING: skip config ignored, unit_test_command is not ctest.` and
   run all tests without placeholders.
4. **Counts and status**: `meta.unit_tests_skipped` and `meta.regression_skipped`
   are set from the reports. Status logic is unchanged. When the existing
   "Skip unit tests" / "Skip regression tests" switches are on, that phase is
   skipped entirely and the config adds nothing for that phase.
5. **Analytics**:
   - `flakiness.compute_flakiness`: skipped simulations are not counted as
     observations and do not set `latest`.
   - `stats_developer.suite_duration`: runs whose index entry has a non-null
     `run_options.skip_config` are excluded, so shortened runs do not look like a
     speed-up.
   - `stats_developer._failing_sim_names` and newly-broken already ignore states
     other than failed/broken; no change.
   - Catalog last status may show `skipped`; that is accurate and kept.

### API

Router prefix `/api/settings/execution/test-skips` (authenticated, like the other
execution settings):

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | list configs |
| POST | `/` | create config (id from slugified name if absent) |
| PUT | `/{id}` | replace one config |
| DELETE | `/{id}` | delete one config |
| GET | `/candidates` | names to pick from, with typical durations |

`/candidates` returns
`{regression: [{name, median_seconds?}], unit: [{name, median_seconds?}]}`.
Regression names come from `catalog.list_catalog_tests(..., include_disabled=False)`
for the configured regtests branch (disabled tests never run, so they need no skip). Unit names are the union of names in
`unit-tests.json` of the 10 most recently finished, non-archived runs across all
branches and architectures. Median durations come from the same runs (skipped
entries ignored). Unit tests only seen in older runs can be added by name.

## Frontend

- **Settings -> Execution**: a third tab, **"Test Skips"**, after Run Profiles and
  Public Settings, without the danger dialog. New `TestSkipConfigsSection.tsx`:
  - config cards with name, description, and "skips N regression, M unit",
    with New / Edit / Delete (`ConfirmDialog` for delete);
  - editor with name, description, and two panels (Regression tests, Unit tests),
    each with a search box, a checkbox list sorted by median duration descending
    (e.g. `DBA-COF-Gauss - 289 s`), a selected count, and an "Add name not listed"
    input. Selected names absent from the candidates stay listed with a
    "not seen recently" hint.
  - API client in `frontend/src/api/testSkips.ts`.
- **Start Run** (`TriggerPage.tsx`): a "Test skip config" select below Run profile,
  default "None (run all tests)". Selecting a config shows a muted line listing the
  skipped names. The request sends `skip_config_id`. "Run again" passes
  `skip_config_id` in the URL. If that config no longer exists, the select falls
  back to None and shows a short note.
- **Live run** (`LiveRunPage.tsx`): `[regression] SKIP <name>` adds a tracker row
  with status `skipped` and no timer.
- **Run detail** (`RunDetailPage.tsx`) and **public run detail**
  (`PublicRunDetailPage.tsx`):
  - "Skip config: <name>" chip with the run options;
  - unit header "X/Y passed - N skipped", skipped rows listed last;
  - regression: skipped simulations collapsed into a "Skipped (N)" group at the
    bottom, name and badge only.
- **Run cards and lists** (`RunSummaryCard.tsx`, dashboard and archive rows): a
  muted "N skipped" chip when `unit_tests_skipped + regression_skipped > 0`.
- **`StatusBadge`**: new `skipped` style (muted, dashed border).

## Error Handling

- Unknown or deleted `skip_config_id` at trigger time: 422 with a clear message;
  nothing is queued.
- Invalid test names or duplicate ids on save: 422 from Pydantic validation, shown
  in the editor.
- Corrupt `test-skip-configs.json`: load logs a warning and returns an empty
  document; save overwrites it atomically.
- Config names not on the run's branch: logged once, ignored.
- Non-ctest unit command: warning line, no skipping, no placeholders.

## Testing

Backend (pytest, `tests/test_test_skips.py` plus additions to existing files):
- model validation (name charset, dedup, sorting, unique ids), store round trip,
  corrupt-file fallback;
- ctest exclude builder: escaping, quoting, non-ctest command left unchanged;
- local regression runner with a fixture tests root: skipped tests are not
  executed, placeholders are appended in order, unknown names are only logged;
- remote regression path filtering (existing remote test fixtures);
- pipeline: counts, unchanged status, snapshot persisted in `run-meta.json` and
  the index, and phase-level skip switches take precedence;
- trigger endpoint: 422 on an unknown id, snapshot frozen at queue time;
- flakiness ignores skipped observations; suite duration excludes skip-config runs;
- old `run-meta.json` and index entries without the new fields still load.

Frontend (vitest):
- Test Skips tab: create, edit with search and checkboxes, delete;
- TriggerPage sends `skip_config_id` and handles a deleted config on rerun prefill;
- RunDetailPage renders the skipped chip, unit skipped rows, and the collapsed
  "Skipped" regression group;
- LiveRunPage tracker shows `SKIP` rows.

## Out of Scope

- Per-architecture skip lists, glob or regex patterns, a default config.
- Skip configs on schedules.
- Ad-hoc per-run test ticking on Start Run (create a config instead).
- Enumerating unit tests by running `ctest -N` on a build host.
