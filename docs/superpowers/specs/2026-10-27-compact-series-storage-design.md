# Compact Series Storage - Design

Date: 2026-10-27
Status: done; conversion, runner, frontend, log gzip and prune all run on production (2026-10-27)

## Progress (2026-10-27)

- `opalx-regsuite migrate-series` is implemented (convert mode and dry run; prune mode
  not yet) in `series.py`, `migration/svg_series.py`, `migration/series_migration.py`.
- Production was converted with the service stopped, after the user backed up both roots:
  - 475 runs converted, 64,139 plots, 0 failures.
  - 3,532 plots anchored, 30 unverifiable (NaN).
  - 3.23 GB of SVGs are now 117 MB of series files.
  - SVGs, `plot` paths and logs are unchanged.
  - Reports are on the server in `~/series-migration-tool/run-{data,archive}.json`.
- Rollout step 2 was done differently:
  - A full read-only dry run on production (same parsing and verification).
  - A full write run on a local copy of older production data (7,464 plots), with
    integrity checks and loading by the deployed data model.
  - No 5.8 GB copy.
- Unreferenced stat SVGs: 397 files in 7 crashed runs without `regression-tests.json`,
  not about 2,100. The spike missed 9 runs under branch names containing `/`; the
  migration finds runs by `run-meta.json` at any depth and converted them.
- Skipped: 1 failed run with a leftover `work/` directory
  (`579-implement-dirichlet-bcs-source-plane-for-p3m/cpu-serial/20261018-202944`).
- Runner, API, frontend, log gzip and settings: commits 85b76da and 4dd2843, deployed
  on production the same day. The user checked the UI and new runs on Daint and Beverin.
  - `series_max_points=None` is resolved to the global default at run start in
    `run_pipeline`, not at trigger time, so triggers, schedules and the CLI share one
    path. The effective value is still recorded in `run_options`.
  - Metrics now also store the `.stat` column `unit`, used as the chart axis label.
    Converted runs have no unit.
- Prune mode (`migrate-series --prune --backup-dir DIR`) is implemented in
  `migration/prune.py`.
  - Local test on a migrated copy: 107 runs, 7,653 SVGs (379 MB) archived to 81 MB of
    verified tarballs and deleted, 1,912 logs gzipped. Run data went from 739 MB to
    90 MB, and integrity results were unchanged.
  - Production backup directory: `/mnt/modern-regsuite-lxc/regsuite-svg-backup`.
- Production prune (2026-10-27, service stopped, about 6 minutes):
  - 559 runs pruned. 64,123 stat SVGs (3.22 GB) went into 475 verified tarballs
    (699 MB), and 13,237 logs were gzipped.
  - Afterwards: 0 stat SVGs, 0 plain logs and 0 `plot` paths remain.
  - SSD runs went from 774 MB to 113 MB, and archive runs from 5.0 GB to 789 MB.
  - Integrity errors from stale manifests went from 106 to 0. A repeat dry run found
    nothing to prune.
- Before the prune, at the user's request, 22 failed runs with no runs-index entry
  were removed (about 33 MB, never shown on the dashboard), including the crashed run
  with the empty `work/` and the 7 runs holding the 397 unreferenced SVGs. Each was
  tarred and verified first to `regsuite-svg-backup/deleted-runs/`.

## Intent

Today every regression run renders one matplotlib SVG per checked metric on the
server (`runner/plotting.py::_write_stat_plot`) and the browser shows them as
`<img>`. Generating them costs server time, and on production they are 62,297
files and 3.2 GB, about 55% of all stored data. The user already moved the
separate static site "regsite" (`regsite/` in the workspace, `tools/pack_run.py`,
`viewer/app.js`) to a layout where each run stores at most about 100 data points
per series in one gzipped JSON file and the browser draws the plots with uPlot.
Server efficiency is the goal; client-side work is explicitly not a concern.

This project brings the same layout to modern-opalx-regsuite and converts every
existing run, both on the SSD (`data_root`) and in cold storage (`archive_root`).
The suite is a live FastAPI server, not a static site, so regsite's static-hosting
restrictions do not apply.

## Goals

- New runs store their plot data as `series.json.gz` (at most N rows per series)
  instead of SVGs. Pass/fail is still computed from all rows of the `.stat` files.
- N is a global setting (default 100), overridable per run in the advanced fields of
  the Start Run page. N = 0 keeps every row.
- The run page draws value and difference plots in the browser.
- Logs are gzipped once a run has finished and still open as text in the browser.
- A migration command converts all existing runs' SVGs into `series.json.gz` and
  verifies every converted curve. A later, separate prune step backs up and deletes
  the SVGs and gzips the old logs.

## Non-goals

- Viewing cold-stored runs without unarchiving (user decision: keep as now). The
  migration still converts archived runs, so they have series once unarchived.
- Keeping raw `.stat` data for new runs (user decision: only the N points).
  References are versioned in `regression-tests-x`.
- Plots on the public run page (it shows tables only today; unchanged).
- Beamline files (`plots/*_beamline.svg`, `plots/*_beamline.json`, 0.48 GB). Unchanged.
- Closing the unauthenticated `/data` mount (see Follow-ups). This project must not
  widen it.
- Changes to regsite.

## Anti-goals

- Losing any verdict, metric value, or log content.
- Writing to production before the migration has run cleanly on a full copy of
  production data.
- Breaking live log streaming (SSE) or the "open log" links.
- Making the server do per-request work for plots (series files are served as-is).

## Evidence this rests on

Measured 2026-10-27, read-only on production; details and sources in the vault note
`investigations/2026.10.27 Compact Series Storage and Legacy SVG Recovery`.

- Production: 572 runs (74 on SSD, 770 MB; 512 in the NFS archive, 5.0 GB).
  Stat SVGs 3.2 GB, logs 2.1 GB, beamline files 0.48 GB.
- Finished runs keep no `.stat` files. The SVGs are the only copy of current-run curves.
- All SVGs come from Matplotlib 3.10.8. Tick labels survive as XML comments, tick
  positions as `<use x= y=>`, curve coordinates with 6 decimals.
- A throwaway extractor parsed all 62,297 production plots with zero failures.
  Checked against `current_value`/`reference_value` in `regression-tests.json`:
  95.9% of curves within 1e-6 of the axis span, 98.6% within 1e-4. The remaining
  3,318 are flat curves at the floating-point floor (axis span below 1e-8 of the
  value), where matplotlib rounded the axis offset label; they are within 1e-9
  relative to the value and become exact by anchoring on the stored last value.
  30 curves have NaN values and cannot be checked.
- matplotlib simplified the lines before writing (median 92 points per curve,
  p90 308), so converted curves are faithful display copies, not raw data.
  58,107 plots also contain the difference curve on its own axis.
- Logs compress about 11x with gzip (319.5 MB to 28.4 MB on local test data).
- The spike scripts live outside the repo (session scratchpad). The logic they used
  is described under "SVG extraction" below.

## Design

### Run directory layout

```
runs/<branch>/<arch>/<run_id>/
    run-meta.json            unchanged, plus run_options.series_max_points
    unit-tests.json          unchanged
    regression-tests.json    unchanged except RegressionMetric.series (bool)
    series.json.gz           NEW: all plot data of the run
    logs/*.log               while the run is live
    logs/*.log.gz            after the run has finished (plain file removed)
    plots/*_beamline.*       unchanged
    artifact-manifest.json   rebuilt after any change to the files above
runs-index/, branches.json   unchanged; they remain the run index
```

`RegressionMetric.plot` stays in the model for unconverted runs and is cleared by the
prune step. `RegressionSimulation.log_file` keeps the logical name
(`logs/<test>-RT.log`); the server resolves the physical `.log` or `.log.gz`.

### `series.json.gz` (schema 2)

A superset of regsite's schema 1, so the shape stays familiar:

```
{"schema": 2,
 "source": "runner" | "svg",          # svg = converted from legacy SVGs
 "max_points": 100,                   # N used; 0 = all rows
 "sims": {<test>: {<container id or "_">: {
     "s":  [...], "rs": [...],        # x of current / reference, shared by all metrics
     "m": {<metric>: {
         "cur": [...], "ref": [...],
         "s": [...], "rs": [...],     # only when this metric has its own x (svg source)
         "d": {"s": [...], "v": [...]}  # current - reference; absent if no common s
     }}
 }}}}
```

- Readers take `metric.s ?? container.s` (and the same for `rs`).
- Values are stored losslessly (Python `repr` of float64). NaN and infinities become
  `null` (`json.dumps(..., allow_nan=False)` after mapping), which uPlot draws as a gap.
- gzip level 9 with `mtime=0`, so identical data gives identical bytes.
- A metric is in the file only if it was plottable under today's `can_plot` rule
  (both series present, lengths match their x, more than one row). Its
  `RegressionMetric.series` is then true.

### Thinning (runner source)

- Current and reference: port regsite's `nearest_rows`/`thin_series` from
  `tools/pack_run.py` unchanged. For each container, take the rows nearest to N
  positions evenly spaced over the s range of run and reference together, so
  samples the two have in common stay aligned. Same fallback when s is not monotonic.
- Difference (user decision: stored, not computed in the browser): compute
  current - reference at full resolution at the common s values, using the existing
  `_common_s_differences` rule (relative 1e-9). Then reduce it to at most N points by
  per-bucket min/max: split the s range into N/2 buckets and keep each bucket's
  minimum and maximum row in s order, plus the first and last row. Narrow spikes in
  the difference survive, which regsite's grid sampling can miss.
- N = 0 skips thinning for all three.

### Max points setting

- Global default: `ExecutionSettings.series_max_points: int = 100` (`ge=0`), edited on
  the Settings page next to the public execution presets. "Reset from config" uses a
  new optional `series_max_points` key in `config.toml`, else 100. The Settings page
  must round-trip the field in its whole-document PUT.
- Per run: `RunOptions.series_max_points: Optional[int]`, a number field in
  `AdvancedRunFields` with the global default as placeholder. The effective value is
  resolved at trigger time and stored in `run-meta.json`, so "Run again" prefills it.
- Schedules use the global default and get no field (same as skip configs).

### Runner

- `regression_results._build_container` stops calling `_write_stat_plot`. It returns
  the full arrays for plottable metrics; thinning happens once per container.
- The regression stage collects series per simulation and rewrites `series.json.gz`
  after each simulation, through a staging file plus `os.replace`, so cancelled or
  crashed runs keep the tests that finished.
- The grid-mismatch warning stays. `runner/plotting.py` goes, and the round-trip
  tests below keep a copy of its plotting code as a fixture generator. `matplotlib`
  stays a dependency because `beamline_viz` uses it.
- Remote and Slurm runs build results locally after fetching outputs, so they need no
  separate path.

### Logs

- Gzipping happens in a post-run step, not inside `run_pipeline`. Writes to
  `pipeline.log` continue after `done status=...` and after today's manifest write:
  the remote/Slurm `finally` cleanup lines, the coordinator's error and timeout lines,
  and the final flush of `_log_tailer`, which reopens `pipeline.log` by path every
  0.5 s. Run the step in the coordinator after the tailer's last flush and after
  `release_run_slot`, plus an equivalent hook for the CLI `run` command.
- The step gzips every `logs/*.log` to `logs/*.log.gz` (staging plus `os.replace`),
  checks that each decompresses to the same bytes, removes the plain file, and then
  rewrites `artifact-manifest.json`.
- A finished run stays in coordinator memory until the next run on its machine, and
  its live page replays the log with `log_path.read_text()`. That replay and every
  other server-side reader of finished-run logs go through one helper that opens
  `.log` or `.log.gz` transparently. The builder must find all readers (SSE replay,
  crash summary, stats, integrity, sitegen).

### Serving

- Series: `GET /api/results/branches/{branch}/archs/{arch}/runs/{run_id}/series`,
  with the same auth dependency as `get_run`. It returns the file with
  `Content-Encoding: gzip`, `application/json`, and a long private cache header for
  finished runs. It returns 404 when the file is missing or the run is cold-stored.
  The frontend fetches it through the existing API client, so the bearer token is sent.
- Logs: a route registered before the `/data` mount handles
  `/data/runs/{branch}/{arch}/{run_id}/logs/{name}.log`. It serves the plain file if
  present, else `{name}.log.gz` with `Content-Encoding: gzip` and
  `text/plain; charset=utf-8`, so existing links keep opening as text. It has the
  same access as `/data` today, with strict path validation (no absolute paths, no
  `..`, resolved path inside `data_root`).
- If the app uses `GZipMiddleware`, check that it leaves these responses alone (it
  skips responses that already set `Content-Encoding`).

### Frontend

- Add `uplot` (MIT, about 50 KB) and a `SeriesPlot` component modelled on regsite's
  viewer (`viewer/app.js`, around lines 420-470):
  - Top panel: current and reference values.
  - Bottom panel: the difference, symmetric around zero, spanning at least
    plus/minus the check's tolerance.
  - Shared cursor between the two panels; theme colours from `useThemeColors`.
- `RunSimulationCard` loads the run's series lazily when a simulation is opened
  (react-query, one fetch per run). It renders `SeriesPlot` for metrics with
  `series: true`. It falls back to today's `<img>` for metrics that only have `plot`
  (unconverted runs), and shows nothing when neither exists.
- When current and reference x differ (svg source, or grids that differ), merge them
  into one ascending x array with `null` gaps (uPlot's default mode).

### SVG extraction (migration)

Productionize the spike logic in its own module (e.g. `migration/svg_series.py`):

- Per axis group (`matplotlib.axis_1` = x, `matplotlib.axis_2` = left y in `axes_1`;
  the first `matplotlib.axis_N` in `axes_2` = difference y), read tick positions from
  `<use ... x= y=>` and labels from the following `<!-- label -->` comment. Labels use
  U+2212 for minus.
- Apply offset/multiplier text found after the ticks: `1e−9`, `+1e3`,
  `1e−11+1.000463999e2`, meaning value = label * scale + offset. Fit pixel to data by
  least squares over all ticks, and fail the plot if fewer than 2 ticks parse.
- Curves are `line2d_N` paths in the axes group, excluding the `legend_N` group:
  `#1f77b4` with width 2 is current, `#ff7f0e` with width 2 is reference, `#808080`
  dashed in `axes_2` is the difference. Paths contain only M/L commands. Drop
  consecutive duplicate vertices (matplotlib repeats the last one).
- Verify each curve's last value against `current_value`/`reference_value`. If the y
  axis has an additive offset and the mismatch exceeds 1e-4 of the axis span, shift
  the curve so its last point equals the stored value, and record it as anchored.
  Record NaN values as unverifiable, and anything else outside tolerance as failed.
- Thin current and reference per metric with `nearest_rows` over their joint s range,
  and the difference with the min/max reduction. These curves have their own x per
  metric, so they use the metric-level `s`/`rs` fields.
- Log-scale axes do not occur (0 found), so a log-axis plot fails loudly rather than
  being guessed.

### Migration command

`opalx-regsuite migrate-series`:

- Options:
  - `--root data|archive|all` (default `data`), `--run BRANCH/ARCH/RUN_ID` (repeatable).
  - `--dry-run`: parse and verify everything, write nothing, print and save the report.
  - `--max-points N` (default: the global setting).
  - `--report PATH`: JSON report.
  - `--prune --backup-dir DIR`: a separate mode, refused without a backup dir.
- Convert mode (default) only adds files, so the old release can still read every run:
  - Skip runs without `run-meta.json`, runs with status `running` or `queued`, runs
    with a `work/` directory, and runs that already have a schema-2 `series.json.gz`
    (idempotent).
  - Write `series.json.gz` and the updated `regression-tests.json` (`series: true`,
    `plot` kept) via staging plus `os.replace`, then rebuild `artifact-manifest.json`.
    Logs are not touched in this mode.
- Report:
  - Per-run and total counts of plots converted, verified, anchored, unverifiable,
    and failed (with reasons), plus bytes before and after. The exit status is
    non-zero if any plot failed.
  - Runs with failed plots keep their SVGs and `plot` paths.
  - Also counted: unreferenced stat SVGs, in runs without `regression-tests.json` or
    not named by any metric. Production has 397, all in 7 crashed runs without a
    report. They are invisible in the UI today and get no series.
- Prune mode, the contract step after the grace period:
  - For runs with a schema-2 series and no failed plots, tar the non-beamline
    `plots/*.svg` (referenced and unreferenced) to
    `DIR/<branch>/<arch>/<run_id>-svgs.tar.gz` and verify the tar.
  - Delete those SVGs, set `plot` to null, gzip the run's logs, and rebuild the manifest.
  - Runs without `regression-tests.json` get the same tar-and-delete for their SVGs
    plus log gzip.
- The command expects the web service to be stopped (the runbook below says so). It
  refuses runs that look active, as above.

### Rollout (production is live)

1. Local: `opalx-regsuite-test-data` with the new code and migration; check the UI.
2. Copy production data read-only to the Mac (`rsync` of both roots, about 5.8 GB).
   Dry run, then a full migration on the copy. The report must match the spike:
   0 failures, about 30 unverifiable. Check the UI against that copy, and run prune
   on the copy too. (Done differently for the conversion; see Progress.)
3. Deploy the code. New runs write series and gzipped logs; old runs keep SVG fallback.
4. Maintenance window with no active run:
   1. Stop the service.
   2. Tar to the NAS: all JSON files of both roots, the whole `data_root`,
      `users_root/_public/` (holds `execution-settings.json`), and `config.toml`.
   3. Run `migrate-series --root data`.
   4. Start the service and spot-check.
5. Same for `--root archive`.
6. Grace period with SVGs and plain logs still present; the user picks its length.
7. Run `migrate-series --prune --backup-dir <NAS path>`.

Rollback until step 7: stop the service and check out the previous release. Then
restore `execution-settings.json` and `config.toml` from the step 4 backup, or delete
the `series_max_points` key from both; the old models use `extra="forbid"` and reject
the key. Start the service. Old runs show their SVGs and logs as before. Runs made
after step 3 show no plots under the old release, and their gzipped logs 404 until
gunzipped. After step 7, rollback needs the SVG tars and gunzipped logs restored.

A dev script under `scripts/` spot-checks converted references against
`regression-tests-x` at each run's `tests_repo_commit`
(`git show <commit>:RegressionTests/<test>/reference/<test>.stat`) for a sample of
plots during step 2.

### Testing

- Thinning: port regsite's behaviour (first and last row kept, at most N rows, shared
  grid alignment, non-monotonic fallback). Diff reduction keeps an injected one-row spike.
- Series writer: NaN becomes null, deterministic bytes, schema fields.
- Extraction round trip: generate SVGs with the old `_write_stat_plot` code from known
  arrays (normal, offset axis, flat curve near the floating-point floor, missing
  difference), extract, compare within tolerance. Also a few real production SVGs
  committed as fixtures.
- Migration: on a temp data root it is idempotent, has a dry run that writes nothing,
  skips active runs, leaves failed plots untouched, and prunes only with a backup.
- Logs: the gzip step checks content, and the serving route returns plain and gzipped
  logs with the right headers and rejects path traversal.
- API: the series endpoint needs auth and returns 404 for cold-stored runs.
- Frontend (vitest): x merging with null gaps, `<img>` fallback, nothing shown when
  neither exists.

## Calls made without the user

- Global default lives in `ExecutionSettings` (Settings page), with a `config.toml` fallback.
- Schedules get no per-schedule N.
- uPlot instead of the already installed recharts, for parity with regsite and its
  canvas performance.
- References are not rebuilt from git; git is only used to spot-check.
- Migration requires the service to be stopped rather than coordinating with it live.
- Rollback to the previous release must work through the grace period. So
  conversion only adds files, legacy logs are gzipped only in the prune step, and
  the backup includes the settings file and `config.toml`.
- The 397 unreferenced stat SVGs are tarred to the backup and deleted in the prune
  step, not converted (user: they can be deleted).
- Log gzip and the final manifest move to a post-run step after the live-log
  tailer's last flush, not inside `run_pipeline` (the reviewer found trailing writes
  there).
- `sitegen` (legacy static export) keeps copying run files; its pages stop showing
  metric plots for runs without SVGs.

## Left to the builder

Module layout and names, helper APIs, the exact report format, cache header values,
plot styling details, and where the log helper lives.

## Follow-ups (separate work)

- `/data` is a `StaticFiles` mount with no auth (`api/app.py`, around line 364), so
  every log and plot under `data_root` is fetchable by URL without login. Fixing it
  needs authenticated links for `<a>` and `<img>` (e.g. the query-token scheme SSE
  already uses).
- Optionally port the stored difference series back to regsite.

## Documentation

After implementation, per the workspace CLAUDE.md: changelog notes, the topic note
(`Static Results Site` or a new results-data topic), and the `data-and-graphs`
guideline (new `series.json.gz` format, gzipped logs) in the vault.
