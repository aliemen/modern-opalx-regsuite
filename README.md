Disclaimer: There is a lot of generated code in here (since this was initially planned to be a small internal testing tool that got kinda out of hand after how good LLMs got...), so don't trust anything that's happening in here. It seems to work fine and from time to time I find security vulnerabilities that I patch, but I haven't reviewed the whole code yet - so no guarantees for anythings! 

## modern-opalx-regsuite

Modern, portable regression test orchestration and web dashboard for OPALX.

### Features

- **Web UI**: React + Tailwind dashboard with login, run trigger, live log streaming (SSE), results browsing, dashboard statistics, and live queue display.
- **Test catalog**: Browse the local `regression-tests-x` clone by branch without checking it out. The catalog shows enabled/disabled tests, `.rt` metric checks, reference data, multi-container references, last status, and flaky suspects.
- **Re-run from results**: A run detail page can prefill Start a Run with the original branch, tests branch, build preset, execution snapshot, and run options.
- **Advanced CMake overrides**: Manual triggers keep basic settings visible while advanced options expand inline. Shared quick selections can insert one-off CMake arguments such as `-DIPPL_GIT_TAG=`; custom args force a clean build and override matching configured `-D` values.
- **Artifact integrity checks**: Runs carry an `artifact-manifest.json`; CLI and API checks verify required JSON, logs, plots, hashes, and referenced artifacts.
- **Flakiness signals**: Dashboard and catalog surfaces flag simulations with mixed pass/fail outcomes in the recent history for the same OPALX branch, regression-tests branch, and architecture.
- **Per-machine run queuing**: Runs are queued per machine instead of rejected. Local and remote machines can run in parallel; only one run per physical host at a time.
- **Dashboard-managed execution profiles**: Public build, machine, environment, and Slurm presets live under `users_root/_public/`; each user combines them with private usernames, SSH keys, and workspace paths in run profiles.
- **Config-driven deployment defaults**: `config.toml` keeps repo/data roots, default branches, host/port/auth paths, and optional deprecated `[[arch_configs]]` only for first-load seeding and legacy compatibility.
- **ProxyJump support**: SSH machine presets can hop through a bastion host — perfect for HPC sites like CSCS Daint via `ela.cscs.ch`.
- **Environment presets**: Public presets support `none`, `modules`, `prologue`, and `uenv`; remote Slurm+uenv still uses `srun --uenv/--view`.
- **Sensitive-data isolation**: `data_root` (which may be shared publicly) contains test/run data plus public execution snapshots. Private usernames, key names, OTPs, passwords, and workspace paths stay under `users_root`.
- **API keys for automation**: Long-lived, scope-limited bearer tokens (managed in Settings -> API keys) let you automate SSH-key rotation from a laptop via the [deploy/opalx-keys.sh](deploy/opalx-keys.sh) bash client - no browser session needed.
- **File-based data model**: JSON + logs + SVG plots on disk, no database. Results live in a separate git repo (`opalx-regsuite-test-data`).
- **Single-command server**: `opalx-regsuite serve` starts the full stack.
- **CLI still works**: All CLI commands (`run`, `user-add`, `migrate-keys`, `gen-data-site`, `del-test`, …) remain available.

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
| `opalx-regsuite run` | Run pipeline from the CLI (local execution only) |
| `opalx-regsuite user-add` | Add/update a web user; auto-creates the per-user directory tree |
| `opalx-regsuite user-del` | Remove a web user |
| `opalx-regsuite migrate-keys --user <name>` | Copy legacy global SSH keys at `~/.config/opalx-regsuite/ssh-keys/` into the per-user directory of `<name>` |
| `opalx-regsuite gen-data-site` | Generate offline static HTML snapshot |
| `opalx-regsuite del-test` | Delete run data |
| `opalx-regsuite rebuild-indexes` | Rebuild `runs-index/` and `branches.json` from disk |
| `opalx-regsuite check-artifacts` | Validate run artifact manifests and referenced files |
| `opalx-regsuite rebuild-artifact-manifests` | Regenerate `artifact-manifest.json` files for indexed runs |

---

### Configuration (`config.toml`)

`config.toml` carries deployment defaults: checkout roots, data/archive roots,
default branches, global commands, web binding, and auth paths. Build,
machine, environment, and Slurm execution definitions are managed in the
dashboard under **Settings -> Execution**. Optional legacy `[[arch_configs]]`
entries are still accepted and are used to seed public build/env/Slurm presets
the first time `users_root/_public/execution-settings.json` is created.

Core fields (set by `init`):

```toml
opalx_repo_root      = "/path/to/opalx"
builds_root          = "/path/to/builds"
data_root            = "/path/to/opalx-regsuite-test-data"
regtests_repo_root   = "/path/to/regression-tests-x"
opalx_info_level     = 2

# Where public execution settings and per-user private state live.
# Must be OUTSIDE data_root since it contains identity-bearing data.
# Default: ~/.config/opalx-regsuite/users
users_root           = "~/.config/opalx-regsuite/users"
```

Deprecated seed-only per-architecture build recipes (optional):

```toml
[[arch_configs]]
arch       = "cpu-serial"
build_jobs = 4
mpi_ranks  = 1
max_mpi_ranks = 4
cmake_args = ["-DBUILD_TYPE=Release", "-DPLATFORMS=SERIAL", "-DOPALX_ENABLE_UNIT_TESTS=ON"]

# Optional seed for a public environment preset.
[arch_configs.env]
style        = "modules"
module_loads = ["module load gcc/15.2.0", "module load openmpi/4.1.6"]

[[arch_configs]]
arch       = "gpu-cuda-a100"
build_jobs = 8
mpi_ranks  = 1
max_mpi_ranks = 4
cmake_args = ["-DBUILD_TYPE=Release", "-DPLATFORMS=CUDA", "-DARCH=AMPERE80"]

[arch_configs.slurm]
partition = "debug"
account = "project"
time = "00:30:00"
tasks_per_node = 1
cpus_per_task = 16
gpus_per_task = 1

# Optional seed for a public environment preset.
# [arch_configs.env]
# style        = "modules"
# module_loads = ["module load gcc/15.2.0", "module swap cuda/12.0 cuda/12.4", "module load openmpi/4.1.6"]
```

After first login, edit these definitions in **Settings -> Execution**. The
public settings store contains:

- CMake quick selections: shared cache-variable names shown as quick-add buttons on the run form
- build presets: CMake args, build jobs, default/max MPI ranks, OPALX info level
- machine presets: local or SSH targets, public host/port/gateway shape, queue key
- environment presets: `none`, `modules`, `prologue`, or `uenv`
- Slurm presets: typed Slurm resources or legacy raw `slurm_args`

Regression commands are generated by the suite, not by `*.local` scripts. By
default each test runs as `mpirun -np <mpi_ranks> <opalx> <test>.in --info
<opalx_info_level>`, with optional per-run overrides from the trigger page or
schedule form. For Slurm-backed profiles, typed Slurm presets are expanded at
trigger time so requested MPI ranks scale `--ntasks`, `--nodes`, and GPU counts
consistently. Legacy `slurm_args` still load for old configs, but new configs
should use typed Slurm presets.

On CSCS Alps/GH200, OPALX unit tests may still launch each CTest test through
`MPIEXEC_EXECUTABLE` even when `CMAKE_TEST_LAUNCHER` is unset. Use
`MPIEXEC_PREFLAGS=--overlap;--cpu-bind=none` for Daint `srun` test launches.
The remote Slurm wrapper also clears inherited `SLURM_CPU_BIND*` variables
inside each job step so nested test launchers do not reuse an invalid CPU mask.

Environment presets accept four styles:

| `style` | Fields | Use case |
|---|---|---|
| `none` (default) | — | Plain shell, no activation |
| `modules` | `lmod_init`, `module_use_paths`, `module_loads` | Classic lmod-managed clusters. `module_loads` entries are complete shell commands, such as `module load gcc/15` or `module swap cuda/12 cuda/12.4`. |
| `prologue` | `prologue` | Free-form shell command, e.g. `uenv start prgenv-gnu/24.7:v3 --view=default` |
| `uenv` | `prologue` | CSCS uenv arguments passed to `uenv run` or Slurm `srun --uenv/--view` |

Web server:
```toml
host = "0.0.0.0"
port = 8000
# bcrypt credential store. Default: ~/.config/opalx-regsuite/users.json
users_file = "~/.config/opalx-regsuite/users.json"
# secret_key is read from OPALX_SECRET_KEY env var (never put it in this file)
```

> **Strict TOML validation**: `SuiteConfig`, `ArchConfig`, `SlurmConfig`,
> `Connection`, `EnvActivation`, and `GatewayEndpoint` all use Pydantic
> `extra="forbid"`. Stale or misspelled keys raise a clear validation error
> at startup instead of being silently ignored.

---

### Execution profiles and remote execution

Remote execution is configured in two layers in the Settings UI:

- **Public execution settings** define build, machine, environment, and Slurm
  presets that any authenticated dashboard user can reference.
- **Private run profiles** combine those public presets with one user's SSH
  username, key names, optional gateway username/key, remote workspace path,
  and cleanup/keepalive behavior.

Legacy `connections.json` files are not modified. On first profile load, the
suite imports existing connections into generated public machine/env presets
and generated private run profiles so the old "arch + connection" behavior is
still available.

#### 1. Upload your SSH key

Navigate to **Settings** → **SSH Keys** in the web UI and upload the private
key. Give it a short name (e.g. `cscs-key`). The key is stored at
`<users_root>/<your-username>/ssh-keys/<name>.pem` with `0o600` permissions
and is **owned by your regsuite user only** — other regsuite users cannot
see it.

#### 2. Define public execution presets

In **Settings** -> **Execution** -> **Public Settings**, edit the shared
presets with the Build, Machine, and Environment cards. Slurm presets live in
the Machine card because they describe queue/allocation behavior for remote
machines. A collapsed read-only JSON export is available for auditing the exact
stored document.

| Field | Example | Notes |
|---|---|---|
| CMake quick selection | `IPPL_GIT_TAG` | Variable name only; the run form inserts `-DIPPL_GIT_TAG=` |
| Build preset | `cuda-daint` | CMake args, build jobs, default/max MPI ranks, OPALX info level |
| Machine preset | `daint-gh200` | Local or SSH target, public host/port/gateway shape, queue key |
| Environment preset | `daint-uenv` | `none`, `modules`, `prologue`, or `uenv` activation |
| Slurm preset | `daint-debug-gh200` | Typed Slurm resources, or legacy raw `slurm_args` when needed |

Public presets should not contain usernames, key names, passwords, OTPs, or
workspace paths. Those stay in each user's private profile.

#### 3. Create a private run profile

In **Settings** -> **Execution** -> **Run Profiles**, click **Add profile** and
select:

| Field | Example | Notes |
|---|---|---|
| Build preset | `cuda-daint` | Becomes the run `arch` for compatibility and data paths |
| Machine preset | `daint-gh200` | Local or remote machine target |
| Environment preset | `daint-uenv` | Optional; controls local/remote environment activation |
| Slurm preset | `daint-debug-gh200` | Optional; remote Slurm allocation/step defaults |
| SSH user / key | `aliemen` / `cscs-key` | Private to your user directory |
| Gateway user / key | `aliemen` / `cscs-key` | Required for key-auth gateways |
| Remote work directory | `/scratch/.../opalx-regsuite` | Private and never written to `data_root` |

Click **Test** (the lightning-bolt icon) on a profile row to open the SSH chain
(gateway included) and run `whoami` as a smoke test. Interactive 2FA gateways
ask for password and OTP only for that test/trigger request; they are never
stored.

#### 4. Start a run with a profile

Go to **Start a Run**, pick:
- **OPALX branch**
- **Regression-tests branch**
- **Run profile**

The profile determines the build preset, machine, environment, Slurm defaults,
private SSH identity, and workspace path. The same build preset can be used in
multiple profiles, for example local modules, remote direct SSH, remote Slurm,
remote Slurm+uenv, or remote Slurm+modules.

The **Advanced** tab accepts one custom CMake argument per line for manual
runs. Empty lines and lines starting with `#` are ignored. Custom `-DKEY=...`
or `-DKEY:type=...` values replace matching values from the selected build
preset; other custom arguments are appended. Any custom CMake argument forces
a clean build so dependency tag changes cannot reuse a stale build tree.

#### Equivalent SSH config

A run profile targeting an SSH machine preset with a key-auth gateway is
equivalent to this `~/.ssh/config`:

```
Host ela
    HostName ela.cscs.ch
    User aliemen
    IdentityFile ~/.ssh/cscs-key
Host daint.alps
    HostName daint.alps.cscs.ch
    User aliemen
    IdentityFile ~/.ssh/cscs-key
    ProxyJump ela
```

…except the SSH state is owned by your regsuite user inside the server, not
by the OS user the server happens to run as.

#### Migrating legacy global SSH keys

Pre-refactor versions stored SSH keys at the global path
`~/.config/opalx-regsuite/ssh-keys/`. After upgrading, run:

```bash
opalx-regsuite migrate-keys --user <your-regsuite-username>
```

…to copy them into the new per-user directory at
`~/.config/opalx-regsuite/users/<name>/ssh-keys/`. The legacy directory is
otherwise unused.

#### Remote workspace layout

The profile's remote workspace persists between runs by default
(`cleanup_after_run = false`), so git repos are only cloned once and builds are
incremental:

```
{profile.work_dir}/
  opalx-src/                        # git clone of OPALX (HTTPS, updated each run)
  regtests/                         # git clone of regression-tests-x
  builds/{branch}/{arch}/build/     # persistent build dir (incremental cmake/make)
  work/{run_id}/{test_name}/        # per-run work dirs (cleaned after each run)
```

Enable `cleanup_after_run` on the profile to delete the entire workspace
after every run.

#### Requirements on the remote machine

- `git` installed with outbound HTTPS access to the repos
- Any compilers/libraries needed by the build (loaded via the selected environment preset)
- The SSH user must have write access to the profile's `work_dir`
- If using a `prologue` env activation, the prologue must keep `git`, `cmake`,
  and `make` available on `PATH` after activation (some `uenv` views strip
  them — use a view that includes a build toolchain)

#### Sensitive-data isolation

`data_root` is treated as publicly shareable. The runner writes public build,
machine, environment, and Slurm snapshot fields into run metadata, but never
private profile data: no SSH usernames, key names, passwords, OTPs, or
workspace paths. Note that build/test stdout/stderr streams verbatim into the
run logs, so if a build prints absolute paths that contain a username (e.g.
`/scratch/snx3000/aliemen/...`), those *will* appear in the logs. If you intend
to share `data_root` publicly, choose a generic-looking `work_dir` in profiles.

---

### API keys and scripted key rotation

Rotating an SSH key from a laptop normally means opening the web UI, clicking
**Settings -> SSH Keys -> Replace**, picking the new file, and confirming. If
you do that daily (e.g. CSCS Daint issues a fresh key every morning), the
suite also exposes a scripted path:

1. Open the web UI, go to **Settings -> API keys**, click **New API key**.
   Name it after the laptop or workflow it will live on (`macbook`,
   `ci-runner`). Pick an expiry. Copy the token shown once; the server only
   keeps a hash.
2. On the laptop, store the token (chmod 600) in a credentials file:

   ```bash
   mkdir -p ~/.config/opalx-regsuite
   cat > ~/.config/opalx-regsuite/credentials <<'EOF'
   OPALX_API_URL="https://opalx.example.com"
   OPALX_API_TOKEN="opalx_<prefix>_<secret>"
   EOF
   chmod 600 ~/.config/opalx-regsuite/credentials
   ```

3. Drop `deploy/opalx-keys.sh` somewhere on `$PATH`:

   ```bash
   opalx-keys list
   opalx-keys upload  cscs-key ./new-cscs-key --cert ./new-cscs-key-cert.pub
   opalx-keys replace cscs-key ./new-cscs-key --cert ./new-cscs-key-cert.pub
   opalx-keys delete  cscs-key
   ```

   `replace` keeps the key's server-side name, so every run profile or legacy
   connection that references it picks up the new credentials on the next run.
   Ideal for short-lived keys.

API keys are **scoped to the SSH-key endpoints only** - a leaked token
cannot read run data, modify profiles/public settings, or mint more tokens.
The only way to get broader access is a browser session (JWT). Rotate or revoke
a key any time in **Settings -> API keys** (the refresh icon and trash icon).

See [deploy/opalx-keys.README.md](deploy/opalx-keys.README.md) for the full
manual (keyboard-macro examples, exit codes, troubleshooting).

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

### Demo data

The repository includes a small sanitized fixture data root under
`demo-data/`. It is generated from selected production runs but strips user
identity and truncates logs. It contains one passing run, one failing run with
real metric deltas, one multi-container example, and one deliberately corrupt
run for integrity tests.

To regenerate it from a local sibling `opalx-regsuite-test-data` checkout:

```bash
python scripts/generate_demo_data.py
```

---

### Data layout

```
data_root/                                 # publicly shareable: only test/run data
  runs/<branch>/<arch>/<run_id>/
    run-meta.json                           # carries public execution snapshot, NOT user/key/work_dir
    artifact-manifest.json                  # generated file inventory with size/hash data
    unit-tests.json
    regression-tests.json
    logs/pipeline.log, cmake.log, build.log, <TestName>-RT.o, ...
    plots/<TestName>_<var>.svg
  runs-index/<branch>/<arch>.json
  branches.json

~/.config/opalx-regsuite/                  # never publicly shared: identity-bearing
  users.json                                # bcrypt credential hashes
  users/_public/
    execution-settings.json                 # public build/machine/env/Slurm presets
  users/<username>/                         # one directory per regsuite user
    profile.json
    run-profiles.json                       # private profile refs, usernames, key names, work dirs
    connections.json                        # legacy named SSH connections, used for migration/compat
    api-keys.json                           # scoped API keys (sha256 hashes, mode 0600)
    ssh-keys/<name>.pem                     # private SSH keys (mode 0600)
```

---

### Run queuing

Runs are queued per **physical machine** rather than rejected when a machine is busy:

- **Local runs**: All runs triggered with a local machine preset share a single
  `local` slot. Only one local run at a time.
- **Remote runs**: Each physical target host gets its own queue, keyed on the
  public machine preset `queue_key` if set, otherwise the SSH host. Two
  regsuite users with profiles targeting the same host correctly serialize
  against each other.
- **Cross-machine parallelism**: A local run and a remote run (or two remote runs on different
  hosts) can execute simultaneously.
- **Auto-start**: When a run finishes, the next queued run on the same machine starts
  automatically.
- **Queue visibility**: The dashboard shows a live "Running Jobs & Queue" panel. Queued runs
  can be cancelled before they start.
- **Run label**: Active/queued runs expose `connection_name` for compatibility.
  Profile-based runs use the public machine preset id (or `local`), never the
  private SSH user, key, or workspace path.

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
| `/catalog` | Test catalog from the local `regression-tests-x` clone |
| `/trigger` | Start a new run (queues if machine is busy) |
| `/live/:runId?` | Live log streaming for a specific run (or the most recent active run) |
| `/results/:branch/:arch` | Run history table |
| `/results/:branch/:arch/:run_id` | Detailed results with plots, metrics, and machine info |
| `/settings` | SSH keys, public execution presets, private run profiles, and API keys |
