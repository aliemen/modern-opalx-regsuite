Disclaimer: There is a lot of generated code in here (since this was initially planned to be a small internal testing tool that got kinda out of hand after how good LLMs got...), so don't trust anything that's happening in here. It seems to work fine and from time to time I find security vulnerabilities that I patch, but I haven't reviewed the whole code yet - so no guarantees for anythings! 

## modern-opalx-regsuite

Modern, portable regression test orchestration and web dashboard for OPALX.

### Features

- **Web UI**: React + Tailwind dashboard with login, run trigger, live log streaming (SSE), results browsing, dashboard statistics, and live queue display.
- **Per-machine run queuing**: Runs are queued per machine instead of rejected. Local and remote machines can run in parallel; only one run per machine at a time.
- **Config-driven**: `config.toml` with per-architecture overrides (`[[arch_configs]]`) and optional Slurm support.
- **File-based data model**: JSON + logs + SVG plots on disk, no database. Results live in a separate git repo (`opalx-regsuite-test-data`).
- **Remote execution**: SSH into a remote machine (e.g. a GPU server) for cmake, build, and test runs. Results are fetched back and processed locally.
- **Single-command server**: `opalx-regsuite serve` starts the full stack.
- **CLI still works**: All CLI commands (`run`, `gen-data-site`, `del-test`, …) remain available.

---

### Setup (production — Proxmox LXC)

**Requirements**: Python 3.10+, Node.js 20+ (Vite requires Node 20.19+ or 22.12+).

```bash
# 0. (If Node.js < 20) Upgrade Node.js — example using NodeSource on Debian/Ubuntu:
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

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
execution_mode = "local"      # "local", "slurm", or "remote"
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

### Remote execution

`execution_mode = "remote"` SSHes into a remote host to run cmake, build, and regression
tests there. Only `.stat` result files are transferred back; all plotting and JSON
generation happen locally using the existing pipeline.

#### 1. Upload your SSH key

Navigate to **Settings** in the web UI (`/settings`) and upload the private key that
grants access to the remote machine. Give it a short name (e.g. `gpu-key`). The key is
stored as `{data_root}/ssh-keys/{name}.pem` with `0o600` permissions.

Alternatively, place the key file there manually before starting the server.

#### 2. Add the remote arch config

```toml
# Optional: HTTPS URLs for the repos to clone on the remote.
# If omitted, derived automatically from 'git remote get-url origin' of your local repos.
opalx_repo_url    = "https://github.com/org/opalx.git"
regtests_repo_url = "https://github.com/org/regression-tests-x.git"

# Paths passed to 'module use' before 'module load' (applies to all archs, including remote).
module_use_paths  = ["/opt/modules/custom"]

[[arch_configs]]
arch              = "gpu-server"
execution_mode    = "remote"
cmake_args        = ["-DBUILD_TYPE=Release", "-DPLATFORMS=CUDA"]
build_jobs        = 8
mpi_ranks         = 1
module_loads      = ["gcc/15.2.0", "cuda/12.0"]

# Remote SSH settings
remote_host       = "gpu-server.example.com"
remote_user       = "opalx"
remote_key_name   = "gpu-key"          # matches the name uploaded in Settings

# Optional tuning (defaults shown)
remote_port       = 22
remote_work_dir   = "/tmp/opalx-regsuite"   # persistent workspace on the remote
remote_cleanup    = false                    # keep workspace between runs (fast incremental builds)
remote_lmod_init  = "/usr/share/lmod/lmod/init/bash"
```

#### Remote workspace layout

The workspace on the remote persists between runs by default (`remote_cleanup = false`),
so git repos are only cloned once and builds are incremental:

```
{remote_work_dir}/
  opalx-src/                        # git clone of OPALX (HTTPS, updated each run)
  regtests/                         # git clone of regression-tests-x
  builds/{branch}/{arch}/build/     # persistent build dir (incremental cmake/make)
  work/{run_id}/{test_name}/        # per-run work dirs (cleaned after each run)
```

Set `remote_cleanup = true` to delete the entire workspace after each run (useful for
one-off builds or disk-constrained machines).

#### Requirements on the remote machine

- `git` installed with outbound HTTPS access to the repos
- Any compilers/libraries needed by the build (loaded via `module_loads`)
- The SSH user must have write access to `remote_work_dir`

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

### Run queuing

Runs are queued per machine rather than rejected when a machine is busy:

- **Local machine**: All architectures with `execution_mode = "local"` (or `"slurm"`) share a
  single "local" slot. Only one local run at a time.
- **Remote machines**: Architectures with `execution_mode = "remote"` are grouped by their
  `remote_host` value. Two archs pointing to the same host share a queue.
- **Cross-machine parallelism**: A local run and a remote run (or two remote runs on different
  hosts) can execute simultaneously.
- **Auto-start**: When a run finishes, the next queued run on the same machine starts
  automatically.
- **Queue visibility**: The dashboard shows a live "Running Jobs & Queue" panel. Queued runs
  can be cancelled before they start.
- **Machine info**: Each run records which machine it ran on. The run detail page shows
  "Executed On" (e.g. `aliemen@192.168.1.223` for remote, `Local` for local).

Queued runs are held in memory. If the server restarts, queued (not-yet-started) runs are
lost. Already-running runs that were interrupted are healed to "failed" on the next startup.

---

### Deployment notes

The server **must** run with a single uvicorn worker (`--workers 1`, the default) because
run queue state is held in process memory. This is enforced by the CLI's `serve` command.

---

### Web pages

| Route | Description |
|---|---|
| `/` | Dashboard — latest run per branch/arch, stats panel, live queue display |
| `/trigger` | Start a new run (queues if machine is busy) |
| `/live/:runId?` | Live log streaming for a specific run (or the most recent active run) |
| `/results/:branch/:arch` | Run history table |
| `/results/:branch/:arch/:run_id` | Detailed results with plots, metrics, and machine info |
| `/settings` | SSH key management |
