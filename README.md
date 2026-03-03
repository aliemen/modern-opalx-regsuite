## modern-opalx-regsuite

Modern, portable regression test orchestration and reporting suite for OPALX.

### Features

- **Config-driven**: Minimal `config.toml` defining OPALX repo, builds root, and data root.
- **CLI-first**: `opalx-regsuite` command to run tests, inspect runs, and generate a static site.
- **File-based data model**: JSON + logs + plots on disk, no database required.
- **Static dashboard**: `gen-data-site` turns the data directory into a static HTML dashboard.
- **Optional trigger service**: Small HTTP service can wrap the CLI for ad-hoc triggering and live log viewing.

### Installation

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `opalx-regsuite` CLI.

### Quick start

1. **Initialize configuration**

```bash
opalx-regsuite init
```

Follow the prompts to set:

- OPALX repository root
- Regression tests repository root
- Builds root (per-branch/per-arch build directories)
- Data root for regression data

2. **Run tests**

```bash
opalx-regsuite run --branch master --arch cpu-serial
```

This will:

- Update and check out the requested branch in your OPALX repo
- Update and check out the configured branch in your regression-tests-x repo
- Configure the build directory with CMake (using `cmake_args`)
- Build OPALX (using `build_command`, default `make -j2`)
- Run unit tests (CTest or a configured command)
- Run regression tests via a configured command or hook
- Write JSON data and logs (including `pipeline.log`) under the data root

3. **Generate static site**

```bash
opalx-regsuite gen-data-site --out-dir site
```

The `site` directory can be served by any static HTTP server, for example:

```bash
python -m http.server --directory site
```

### Configuration

Configuration is stored in a small `config.toml` file, by default in the project root. You can override its location with `--config` on each command or by setting `OPALX_REGSUITE_CONFIG`.

The config includes:

- `opalx_repo_root`: Path to your OPALX source checkout.
- `regtests_repo_root`: Path to your regression-tests-x checkout.
- `regtests_branch`: Branch for the regression-tests-x repo (set once).
- `builds_root`: Root directory for per-branch/per-architecture builds.
- `data_root`: Root directory for regression and unit test data.
- `cmake_args`: Extra arguments for the CMake configure step (e.g. build type, platforms, unit-test flags).
- `build_command`: Build command to run in the build directory (default `make -j2`).
- `unit_test_command`: Command to execute unit tests in the build directory.
- `regression_test_command`: Command to execute regression tests (optional).

### Extending

- **Unit tests**: Adjust the configured unit test command to match your CTest invocation or custom harness.
- **Regression tests**: Plug in your own regression runner and have it emit JSON and plots according to the data model.
- **Dashboard**: Extend or re-style the Jinja2 templates under `modern_opalx_regsuite/templates`.

