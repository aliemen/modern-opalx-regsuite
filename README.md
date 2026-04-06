## modern-opalx-regsuite

Modern, portable regression test orchestration and web dashboard for OPALX.

### Features

- **Web UI**: React + Tailwind dashboard with login, run trigger, live log streaming (SSE), and results browsing.
- **Config-driven**: `config.toml` with per-architecture overrides (`[[arch_configs]]`) and optional Slurm support.
- **File-based data model**: JSON + logs + SVG plots on disk, no database. Results live in a separate git repo (`opalx-regsuite-test-data`).
- **Single-command server**: `opalx-regsuite serve` starts the full stack.
- **CLI still works**: All CLI commands (`run`, `gen-data-site`, `del-test`, …) remain available.

---

### Setup (production — Proxmox LXC)

```bash
# 1. Clone the repo and install
git clone <this-repo> /home/opalx/modern-opalx-regsuite
cd /home/opalx/modern-opalx-regsuite
python3 -m venv .venv
source .venv/bin/activate
make install          # builds frontend + installs Python package

# 2. Configure
opalx-regsuite init   # creates config.toml interactively

# 3. Set the JWT secret key (required)
export OPALX_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# Or put it in /etc/opalx/secrets (see deploy/setup.sh)

# 4. Add your first user
opalx-regsuite user-add --username admin

# 5. Start the server
opalx-regsuite serve --host 0.0.0.0 --port 8000
```

For a fully automated setup (creates system user, secrets file, systemd unit):
```bash
sudo bash deploy/setup.sh
```

See [deploy/nginx.conf](deploy/nginx.conf) for the nginx reverse proxy config (required for SSE to work correctly).

---

### Quick start (local development)

```bash
# Install dependencies
make install

# Generate a secret key and export it
export OPALX_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Configure
opalx-regsuite init

# Add a user
opalx-regsuite user-add --username dev

# Start the server (serves the built frontend + API on :8000)
opalx-regsuite serve

# Or run frontend dev server with HMR + API proxy:
cd frontend && npm run dev   # frontend on :5173, proxies /api → :8000
```

---

### CLI Commands

| Command | Description |
|---|---|
| `opalx-regsuite init` | Interactive config.toml setup |
| `opalx-regsuite serve` | Start the web server |
| `opalx-regsuite run` | Run pipeline from the CLI |
| `opalx-regsuite user-add` | Add/update a web user |
| `opalx-regsuite user-del` | Remove a web user |
| `opalx-regsuite gen-data-site` | Generate offline static HTML snapshot |
| `opalx-regsuite del-test` | Delete run data |

---

### Configuration (`config.toml`)

Core fields (set by `init`):

```toml
opalx_repo_root      = "/path/to/opalx"
builds_root          = "/path/to/builds"
data_root            = "/path/to/opalx-regsuite-test-data"
regtests_repo_root   = "/path/to/regression-tests-x"
```

Per-architecture overrides (optional, can have multiple):

```toml
[[arch_configs]]
arch           = "cpu-serial"
execution_mode = "local"      # "local" or "slurm"
build_jobs     = 4
mpi_ranks      = 1
cmake_args     = ["-DBUILD_TYPE=Release", "-DPLATFORMS=SERIAL", "-DOPALX_ENABLE_UNIT_TESTS=ON"]

[[arch_configs]]
arch           = "gpu-cuda-a100"
execution_mode = "slurm"
build_jobs     = 8
mpi_ranks      = 1
slurm_args     = ["--partition=gpu", "--gres=gpu:1", "--time=02:00:00"]
module_loads   = ["gcc/15.2.0", "openmpi/4.1.6_slurm", "cuda/12.0"]
cmake_args     = ["-DBUILD_TYPE=Release", "-DPLATFORMS=CUDA", "-DARCH=AMPERE80"]
```

Web server:
```toml
host = "0.0.0.0"
port = 8000
users_file = "users.json"
# secret_key is read from OPALX_SECRET_KEY env var (never put it in this file)
```

---

### Environment Variables

| Variable | Purpose |
|---|---|
| `OPALX_SECRET_KEY` | JWT signing key (required, 256-bit hex) |
| `OPALX_REGSUITE_CONFIG` | Path to config.toml (optional) |
| `OPALX_DATA_ROOT` | Override `data_root` at runtime (optional) |

---

### Importing old run data

```bash
git clone <opalx-regsuite-test-data> /srv/opalx/test-data
# Set data_root = "/srv/opalx/test-data" in config.toml
# All old runs appear in the dashboard immediately — no migration needed.
```

---

### Data layout

```
data_root/
  runs/<branch>/<arch>/<run_id>/
    run-meta.json
    unit-tests.json
    regression-tests.json
    logs/pipeline.log, cmake.log, build.log, <TestName>-RT.o, ...
    plots/<TestName>_<var>.svg
  runs-index/<branch>/<arch>.json
  branches.json
```

---

### Web pages

| Route | Description |
|---|---|
| `/` | Dashboard — latest run per branch/arch |
| `/trigger` | Start a new run |
| `/live` | Live log streaming for the active run |
| `/results/:branch/:arch` | Run history table |
| `/results/:branch/:arch/:run_id` | Detailed results with plots and metrics |
