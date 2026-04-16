Disclaimer: There is a lot of generated code in here (since this was initially planned to be a small internal testing tool that got kinda out of hand after how good LLMs got...), so don't trust anything that's happening in here. It seems to work fine and from time to time I find security vulnerabilities that I patch, but I haven't reviewed the whole code yet - so no guarantees for anythings! 

## modern-opalx-regsuite

Modern, portable regression test orchestration and web dashboard for OPALX.

### Features

- **Web UI**: React + Tailwind dashboard with login, run trigger, live log streaming (SSE), results browsing, dashboard statistics, and live queue display.
- **Per-machine run queuing**: Runs are queued per machine instead of rejected. Local and remote machines can run in parallel; only one run per physical host at a time.
- **Config-driven build recipes**: `config.toml` with per-architecture overrides (`[[arch_configs]]`) carrying only the *build recipe* (cmake args, build jobs, mpi ranks, env activation).
- **Per-user named connections**: Each authenticated regsuite user manages their own SSH keys and named *connections* (target host, user, key, optional ProxyJump gateway, environment activation) via the Settings UI. At trigger time the user picks a run config + a connection (or "Local").
- **ProxyJump support**: Connections can hop through a bastion host — perfect for HPC sites like CSCS Daint via `ela.cscs.ch`.
- **Two env activation styles**: `module load` (lmod) or free-form `prologue` commands like `uenv start prgenv-gnu/24.7:v3 --view=default`.
- **Sensitive-data isolation**: `data_root` (which may be shared publicly) contains only test/run data + the user-chosen connection name. Identity-bearing state (SSH keys, hostnames, usernames, work dirs) lives under `~/.config/opalx-regsuite/`.
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

---

### Configuration (`config.toml`)

`config.toml` carries only the **build recipe**. SSH targets, gateways, keys
and remote work dirs live in *per-user named connections*, managed in the
Settings UI (see [Connections](#connections-and-remote-execution) below).

Core fields (set by `init`):

```toml
opalx_repo_root      = "/path/to/opalx"
builds_root          = "/path/to/builds"
data_root            = "/path/to/opalx-regsuite-test-data"
regtests_repo_root   = "/path/to/regression-tests-x"

# Where per-user state (ssh-keys, connections.json, profile.json) lives.
# Must be OUTSIDE data_root since it contains identity-bearing data.
# Default: ~/.config/opalx-regsuite/users
users_root           = "~/.config/opalx-regsuite/users"
```

Per-architecture build recipes (optional, can have multiple):

```toml
[[arch_configs]]
arch       = "cpu-serial"
build_jobs = 4
mpi_ranks  = 1
cmake_args = ["-DBUILD_TYPE=Release", "-DPLATFORMS=SERIAL", "-DOPALX_ENABLE_UNIT_TESTS=ON"]

# Optional: environment activation for LOCAL runs of this arch.
# (Remote runs use the connection's env activation instead.)
[arch_configs.env]
style        = "modules"
module_loads = ["gcc/15.2.0", "openmpi/4.1.6"]

[[arch_configs]]
arch       = "gpu-cuda-a100"
build_jobs = 8
mpi_ranks  = 1
cmake_args = ["-DBUILD_TYPE=Release", "-DPLATFORMS=CUDA", "-DARCH=AMPERE80"]

[arch_configs.env]
style        = "modules"
module_loads = ["gcc/15.2.0", "openmpi/4.1.6", "cuda/12.0"]
```

The `[arch_configs.env]` sub-table accepts three styles:

| `style` | Fields | Use case |
|---|---|---|
| `none` (default) | — | Plain shell, no activation |
| `modules` | `lmod_init`, `module_use_paths`, `module_loads` | Classic lmod-managed clusters |
| `prologue` | `prologue` | Free-form shell command, e.g. `uenv start prgenv-gnu/24.7:v3 --view=default` |

Web server:
```toml
host = "0.0.0.0"
port = 8000
# bcrypt credential store. Default: ~/.config/opalx-regsuite/users.json
users_file = "~/.config/opalx-regsuite/users.json"
# secret_key is read from OPALX_SECRET_KEY env var (never put it in this file)
```

> **Strict TOML validation**: `SuiteConfig`, `ArchConfig`, `Connection`,
> `EnvActivation`, and `GatewayEndpoint` all use Pydantic
> `extra="forbid"`. Stale or misspelled keys raise a clear validation error
> at startup instead of being silently ignored.

---

### Connections and remote execution

Remote execution is configured per-user via **named connections** in the
Settings UI, not in `config.toml`. Each connection captures everything needed
to reach a specific remote target, including (optionally) a `ProxyJump`
gateway for hopping through a bastion host.

#### 1. Upload your SSH key

Navigate to **Settings** → **SSH Keys** in the web UI and upload the private
key. Give it a short name (e.g. `cscs-key`). The key is stored at
`<users_root>/<your-username>/ssh-keys/<name>.pem` with `0o600` permissions
and is **owned by your regsuite user only** — other regsuite users cannot
see it.

#### 2. Create a connection

In **Settings** → **Connections**, click **Add connection** and fill in:

| Field | Example | Notes |
|---|---|---|
| Name | `daint-cpu` | Avoid embedding usernames or hostnames here — this label is the only identity surface that may end up in publicly-shareable run logs. |
| Description | `CSCS Alps Daint, CPU partition` | Optional |
| Host / User / Port | `daint.alps.cscs.ch` / `aliemen` / `22` | The target machine |
| SSH key | `cscs-key` | Pick from the dropdown of your uploaded keys |
| Use ProxyJump | ☑ | Enable to hop through a bastion |
| Gateway host / user / port / key | `ela.cscs.ch` / `aliemen` / `22` / `cscs-key` | Bastion settings |
| Remote work directory | `/scratch/snx3000/aliemen/opalx-regsuite` | Persistent workspace on the target |
| Wipe work directory after every run | ☐ | Off keeps incremental builds; on is good for disk-constrained machines |
| Environment activation | `prologue` | Or `modules` or `none` |
| Prologue command | `uenv start prgenv-gnu/24.7:v3 --view=default` | Free-form shell command prepended to every remote command |

Click **Test** (the lightning-bolt icon) on a connection row to open the SSH
chain (gateway included) and run `whoami` as a smoke test.

#### 3. Start a run on a connection

Go to **Start a Run**, pick:
- **OPALX branch**
- **Run config** (the architecture / build recipe from `config.toml`)
- **Connection** (your named connection, or `Local`)

The combination is independent: the same arch can be run on Local *or* on
any remote target, depending on which connection you pick.

#### Equivalent SSH config

A connection of the form below is equivalent to this `~/.ssh/config`:

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

The workspace on the remote persists between runs by default
(`cleanup_after_run = false`), so git repos are only cloned once and builds
are incremental:

```
{connection.work_dir}/
  opalx-src/                        # git clone of OPALX (HTTPS, updated each run)
  regtests/                         # git clone of regression-tests-x
  builds/{branch}/{arch}/build/     # persistent build dir (incremental cmake/make)
  work/{run_id}/{test_name}/        # per-run work dirs (cleaned after each run)
```

Enable `cleanup_after_run` on the connection to delete the entire workspace
after every run.

#### Requirements on the remote machine

- `git` installed with outbound HTTPS access to the repos
- Any compilers/libraries needed by the build (loaded via the connection's env activation)
- The SSH user must have write access to the connection's `work_dir`
- If using a `prologue` env activation, the prologue must keep `git`, `cmake`,
  and `make` available on `PATH` after activation (some `uenv` views strip
  them — use a view that includes a build toolchain)

#### Sensitive-data isolation

`data_root` is treated as publicly shareable. The runner writes only the
**user-chosen connection name** into run metadata and log headers — never
the SSH host, user, key, or work_dir. Note that build/test stdout/stderr
streams verbatim into the run logs, so if a build prints absolute paths
that contain a username (e.g. `/scratch/snx3000/aliemen/...`), those *will*
appear in the logs. If you intend to share `data_root` publicly, choose a
generic-looking `work_dir` for your connections.

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

   `replace` keeps the key's server-side name, so every connection that
   references it picks up the new credentials on the next run. Ideal for
   short-lived keys.

API keys are **scoped to the SSH-key endpoints only** - a leaked token
cannot read run data, modify connections, or mint more tokens. The only way
to get broader access is a browser session (JWT). Rotate or revoke a key
any time in **Settings -> API keys** (the refresh icon and trash icon).

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

### Data layout

```
data_root/                                 # publicly shareable: only test/run data
  runs/<branch>/<arch>/<run_id>/
    run-meta.json                           # carries connection_name, NOT host/user/key
    unit-tests.json
    regression-tests.json
    logs/pipeline.log, cmake.log, build.log, <TestName>-RT.o, ...
    plots/<TestName>_<var>.svg
  runs-index/<branch>/<arch>.json
  branches.json

~/.config/opalx-regsuite/                  # never publicly shared: identity-bearing
  users.json                                # bcrypt credential hashes
  users/<username>/                         # one directory per regsuite user
    profile.json
    connections.json                        # named SSH connections
    api-keys.json                           # scoped API keys (sha256 hashes, mode 0600)
    ssh-keys/<name>.pem                     # private SSH keys (mode 0600)
```

---

### Run queuing

Runs are queued per **physical machine** rather than rejected when a machine is busy:

- **Local runs**: All runs triggered with the `Local` connection share a single
  `local` slot. Only one local run at a time.
- **Remote runs**: Each physical target host gets its own queue, keyed on
  `connection.host`. Two regsuite users with different connections to the
  same host correctly serialize against each other (so they don't trash
  each other's `work_dir`).
- **Cross-machine parallelism**: A local run and a remote run (or two remote runs on different
  hosts) can execute simultaneously.
- **Auto-start**: When a run finishes, the next queued run on the same machine starts
  automatically.
- **Queue visibility**: The dashboard shows a live "Running Jobs & Queue" panel. Queued runs
  can be cancelled before they start.
- **Connection name**: Each run records the user-chosen connection name
  (e.g. `daint-cpu`, `local`) — never the underlying SSH host, user, or key.

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
| `/settings` | SSH key management + named SSH connections + API keys for scripted access (per-user) |
