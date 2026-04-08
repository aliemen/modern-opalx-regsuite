# Changelog

## 2026-04-08 — Per-user connections + ProxyJump-capable RemoteExecutor

A large architectural refactor that decouples *what to build* from *where to
run it*, makes SSH state per-user, adds full ProxyJump support, and treats
`data_root` as publicly shareable.

### Why this happened

Before this change:

- All SSH/remote configuration lived inside per-architecture blocks in
  `config.toml` (`ArchConfig.execution_mode = "remote"` plus a flock of
  `remote_*` fields). The same `ArchConfig` carried both *build recipe*
  fields (cmake args, build jobs, mpi ranks, module loads) **and**
  *execution target* fields (host, user, key, work_dir).
- SSH keys were stored in a single global directory shared by every regsuite
  user. There was no notion of per-user state.
- The `RemoteExecutor` only knew how to make a direct SSH connection — no
  `ProxyJump` support, so HPC sites that require a bastion (CSCS Daint via
  `ela.cscs.ch`, etc.) were unreachable.
- `RunMeta` and `RunIndexEntry` (which live under `data_root`) carried
  `execution_host` and `execution_user`, leaking SSH identifiers into
  whatever the user might publicly share.

The motivating user story was running OPALX regression tests on CSCS Daint
through the `ela` jump host, while keeping the SSH identity per-regsuite-user
(so two collaborators logging into the same regsuite server use their own
HPC accounts) and keeping `data_root` clean enough to publish.

### What changed for users

**`config.toml` is now build-recipe only.** `ArchConfig` lost
`execution_mode`, all `remote_*` fields, and the flat `module_loads` list.
A nested `[arch_configs.env]` sub-table replaces `module_loads` with a
unified `EnvActivation` that supports three styles:

| `style` | Fields | Purpose |
|---|---|---|
| `none` | — | Plain shell |
| `modules` | `lmod_init`, `module_use_paths`, `module_loads` | lmod-style activation |
| `prologue` | `prologue` | Free-form shell command (e.g. `uenv start prgenv-gnu/24.7:v3 --view=default`) |

**Per-user state lives at `~/.config/opalx-regsuite/users/<username>/`.**
Each authenticated regsuite user owns:

```
~/.config/opalx-regsuite/users/<username>/
    profile.json            # display metadata
    connections.json        # list of named connections
    ssh-keys/<name>.pem     # private SSH keys (mode 0600)
```

The directory is auto-created in two places: (a) `opalx-regsuite user-add`
materializes it as part of adding a user, and (b) a new
`require_user_paths` FastAPI dependency idempotently `mkdir`s it on every
authenticated request, so users that existed before this refactor self-heal
on first API call.

`users.json` (bcrypt credentials) **stays a single global file** and its
default location moved from `./users.json` (project cwd) to
`~/.config/opalx-regsuite/users.json`. The old default was already not
under `data_root`, but the new one makes the location stable and explicit.

**Connections are first-class.** Each user manages a set of named
connections via Settings → Connections in the web UI. A connection captures:

- Target SSH endpoint: `host`, `user`, `port`, `key_name`
- Optional ProxyJump gateway: `host`, `user`, `port`, `key_name`
- Remote workspace: `work_dir`, `cleanup_after_run`
- Environment activation: same `EnvActivation` shape as `ArchConfig.env`
- A user-chosen `name` and optional `description`

The new connection form supports the full SSH layout — host, user, key
selector, "Use ProxyJump" toggle revealing nested gateway fields, work_dir,
cleanup, env style switcher with conditional field groups for modules /
prologue. There's also a **Test** button (the lightning-bolt icon) that
opens the SSH chain (gateway included) and runs `whoami`.

**At trigger time, the user picks a connection.** The Start-a-Run page got
a new "Connection" dropdown after the Run config picker. The default option
is `Local`. Pick a connection to run on a specific remote target instead.
The combination of (run config × connection) is independent — the same
`cpu-serial` arch can be run on Local, on Daint via gateway, or anywhere
else.

**ProxyJump just works.** Fabric's `Connection(gateway=Connection(...))`
parameter is wired into `RemoteExecutor`. The gateway is built lazily and
cached on the executor instance, then explicitly closed in `RemoteExecutor.close()`
(Fabric's own `close()` does **not** cascade to the gateway).

**SSH key management is per-user.** `/api/settings/ssh-keys` now reads/writes
under the calling user's directory. Key uploads use atomic `O_CREAT | O_EXCL |
O_WRONLY` with mode `0o600` (no 0644 race window). Key deletion is **blocked
with HTTP 409 Conflict** when the key is referenced by any of the user's
connections (or their gateways) — the response lists the dependent
connection names so the UI can tell the user what to unlink first.

**Sensitive-data isolation.** `data_root` is now treated as publicly
shareable. The data model dropped these leaky fields:

- `RunMeta.execution_host`, `RunMeta.execution_user`
- `RunIndexEntry.execution_host`

Both gained a single non-sensitive `connection_name: Optional[str]` (the
user-chosen connection label, or `"local"`). The `RemoteExecutor` log
headers and the `_run_regression_suite_remote` summary lines were
sanitized to use `connection_name` only — never the SSH host, user, or
work_dir. The wrapped command (`cd <work_dir> && source <init> && module load
... && <cmd>`) is built in memory only and is **never** written to any
log file under `data_root`. Only the user-meaningful `<cmd>` lands in the
log header.

There is one residual concern: stdout/stderr from build/test commands
streams verbatim into `logs/*.log`. If a build prints absolute paths
containing a username (e.g. `/scratch/snx3000/aliemen/...`), those will
appear in the logs and we cannot regex-sanitize bytes mid-stream reliably.
The README now documents this and recommends choosing a generic-looking
`work_dir` if `data_root` will be publicly shared. Moving `logs/` out of
`data_root` entirely is recorded as a follow-up.

**Strict TOML validation.** `SuiteConfig`, `ArchConfig`, `Connection`,
`EnvActivation`, and `GatewayEndpoint` all use Pydantic
`model_config = ConfigDict(extra="forbid")`. Stale or misspelled keys raise
a clear validation error at startup instead of being silently ignored
(Pydantic v2 default is `ignore`).

**New CLI command: `opalx-regsuite migrate-keys --user <name>`.** Copies
existing SSH keys from the legacy global location
(`~/.config/opalx-regsuite/ssh-keys/`) into the per-user directory
`~/.config/opalx-regsuite/users/<name>/ssh-keys/`. Pre-existing per-user
keys with the same name are skipped (not overwritten).

### What changed for developers (architectural notes)

**`RemoteExecutor` constructor signature**:

```python
RemoteExecutor(
    host, user, key_path, port=22,
    connection_name="remote",        # NEW: used only for log labels
    gateway=None,                    # NEW: Optional[GatewayEndpoint]
    gateway_key_path=None,           # NEW: Optional[Path]
    env=None,                        # NEW: Optional[EnvActivation]
    pipeline_log_path=None,
)
```

The constructor takes **already-resolved** key paths — it does not look up
keys on disk. Resolution lives in
`user_store.resolve_connection_key_paths(cfg, username, conn)` in the API
layer. The runner is user-agnostic.

`run_command` lost its `module_loads` / `module_use_paths` / `lmod_init`
parameters; environment activation is internal to the executor via the
`env` constructor argument and `_build_env_preamble()`. The preamble is
auto-applied to every `run_command`, including `git_clone_or_update`'s
git operations (so a `prologue` like `uenv start ...` had better keep
`git` on `PATH`).

`ensure_dir`, `path_exists`, `cleanup` continue to call `self.conn.run()`
directly with no preamble — they only need bash builtins / coreutils.

A new `RemoteExecutor.whoami()` method is the authoritative connection
test, used by `POST /api/settings/connections/{name}/test`.

**`run_pipeline` signature**:

```python
def run_pipeline(
    cfg, branch, arch, run_id=None,
    skip_unit=False, skip_regression=False, cancel_event=None,
    connection: Optional[Connection] = None,        # NEW
    target_key_path: Optional[Path] = None,         # NEW
    gateway_key_path: Optional[Path] = None,        # NEW
    repo_locks=None,
)
```

Dropped: `execution_host`, `execution_user`. The runner derives
`is_remote = connection is not None` and pulls everything else off the
`Connection` object. The `_validate_remote_config(ac)` helper was deleted —
Pydantic enforces required Connection fields at the model level.

**`ActiveRun` / `QueuedRun`**: dropped `execution_host`, `execution_user`.
Added `connection_name: str` (public, exposed in `/api/runs/queue` JSON)
plus three in-memory-only fields: `connection: Optional[Connection]`,
`target_key_path: Optional[Path]`, `gateway_key_path: Optional[Path]`.
The connection is loaded from disk *once* at trigger time and passed
through the queue — the coordinator never re-reads it.

**`resolve_machine_id` is now `(connection: Optional[Connection]) -> str`.**
Returns `connection.host` for remote runs and `"local"` otherwise. Just the
host string, no `(host, user)` tuple — physical machine identity, not
per-user. Two regsuite users with different connections to the same
`daint.alps.cscs.ch` correctly serialize against each other.

**New module: `modern_opalx_regsuite/user_store.py`**. Owns the per-user
filesystem layout and connections.json CRUD. Functions: `user_dir`,
`ensure_user_dir`, `user_keys_dir`, `connections_path`, `load_connections`,
`save_connections`, `get_connection`, `upsert_connection`, `delete_connection`,
`connections_referencing_key`, `resolve_connection_key_paths`. Includes a
module-level `dict[str, asyncio.Lock]` keyed on username so concurrent
`PUT`/`POST`/`DELETE` requests for the same user serialize their
read-modify-write of `connections.json`.

**New API router: `modern_opalx_regsuite/api/connections.py`**. Full CRUD
under `/api/settings/connections`:

| Method | Path | Purpose |
|---|---|---|
| `GET`    | `/api/settings/connections`              | List the calling user's connections |
| `POST`   | `/api/settings/connections`              | Create (validates referenced key exists, 422 if not, 409 if name dup) |
| `GET`    | `/api/settings/connections/{name}`       | Fetch one |
| `PUT`    | `/api/settings/connections/{name}`       | Replace one (full body, no rename) |
| `DELETE` | `/api/settings/connections/{name}`       | Delete one |
| `POST`   | `/api/settings/connections/{name}/test`  | Open the SSH chain and run `whoami` |

All endpoints use `require_user_paths` so the user dir self-heals on first
access. The test endpoint runs the blocking SSH call in a worker thread via
`asyncio.to_thread` so it doesn't stall the event loop.

**New API endpoint: `GET /api/auth/me`**. Returns `{username}`. Side effect:
materializes the user dir. The frontend currently doesn't need this for
display (the JWT carries the username, and the new connections endpoints
already operate on the calling user implicitly), but it's there for future
use and as the authoritative way for the frontend to learn its identity.

**Frontend additions**:

- `frontend/src/api/connections.ts` — full CRUD client + `LOCAL_CONNECTION` sentinel.
- `frontend/src/api/user.ts` — `getCurrentUser()` for `/api/auth/me`.
- `frontend/src/components/ConnectionForm.tsx` — the create/edit form, with
  conditional gateway fields and env-style switcher.
- `frontend/src/pages/SettingsPage.tsx` gained a Connections section below
  the existing SSH Keys section. SSH-key delete handler decodes the new 409
  response and surfaces the dependent-connection list to the user.
- `frontend/src/pages/TriggerPage.tsx` got a Connection select after the
  arch select; defaults to `Local`.
- `TriggerRequest` interface in `frontend/src/api/runs.ts` gained the
  optional `connection_name` field.

### Migration steps (for the operator)

The cut is **hard** — `extra="forbid"` will reject stale fields loudly at
startup. Required edits:

1. **`config.toml`**: Remove from each `[[arch_configs]]` block: `execution_mode`,
   `remote_host`, `remote_user`, `remote_port`, `remote_key_name`,
   `remote_work_dir`, `remote_cleanup`, `remote_lmod_init`. Move
   `module_loads = [...]` (and the SuiteConfig-level `module_use_paths`
   if you had it) into a `[arch_configs.env]` sub-table:
   ```toml
   [[arch_configs]]
   arch       = "cpu-serial"
   build_jobs = 4
   cmake_args = [...]

   [arch_configs.env]
   style        = "modules"
   module_loads = ["gcc/15.2.0"]
   ```

2. **`users.json`**: Move from the project root (or wherever it currently
   is) to `~/.config/opalx-regsuite/users.json`. Or set `users_file`
   explicitly in `config.toml` to point at the old location.

3. **SSH keys**: Run `opalx-regsuite migrate-keys --user <name>` to copy
   pre-existing keys from `~/.config/opalx-regsuite/ssh-keys/` into the
   new per-user dir at `~/.config/opalx-regsuite/users/<name>/ssh-keys/`.

4. **Recreate connections**: Any remote arch you used to have in `config.toml`
   must now be created as a Connection via the Settings UI (or by hand-editing
   `~/.config/opalx-regsuite/users/<name>/connections.json`).

5. **Existing run history**: Old `run-meta.json` and `runs-index/*.json`
   files written by the pre-refactor code still contain `execution_host` /
   `execution_user`. These keys are silently ignored on read (we use
   `extra="ignore"` on `RunMeta` and `RunIndexEntry` for backward compat),
   but they remain on disk. If `data_root` is about to be made public,
   either run `opalx-regsuite rebuild-indexes` and write a one-shot script
   to scrub the per-run `run-meta.json` files, or simply start fresh.

### Test coverage

A self-contained backend smoke test against FastAPI's `TestClient`
exercises the full flow end-to-end: login → `/me` → user dir auto-creation
→ SSH key upload (verifying mode 0600) → list keys → create connection
with gateway + prologue env → list connections → duplicate name → 409 →
missing key → 422 → delete in-use key → 409 with dependent_connections →
delete connection → delete (now-unblocked) key → trigger run with missing
connection → 404. All 12 assertions pass.

Sensitive-data guarantees are also verified at the model level by Pydantic:
`RunMeta` and `RunIndexEntry` have `connection_name` and no
`execution_host`/`execution_user`; `SuiteConfig` and `ArchConfig` reject
stale fields with clear validation errors.

Frontend `tsc --noEmit` passes against `tsconfig.app.json`, and `vite build`
produces a clean production bundle.

### Files changed

**Backend**

| File | Change |
|---|---|
| `modern_opalx_regsuite/config.py` | New `EnvActivation`, `GatewayEndpoint`, `Connection` models. New `users_root` field + `resolved_users_root` property. `users_file` default moved to `~/.config/opalx-regsuite/users.json`. Stripped `execution_mode` and all `remote_*` from `ArchConfig`; replaced `module_loads` with nested `env`. `extra="forbid"` on all relevant models. `save_config` rewrites `[arch_configs.env]` sub-tables. |
| `modern_opalx_regsuite/data_model.py` | Removed `execution_host`/`execution_user`. Added `connection_name` to both `RunMeta` and `RunIndexEntry`. `extra="ignore"` for backward compat with old files on disk. |
| `modern_opalx_regsuite/user_store.py` | **NEW.** Per-user FS layout, connections.json CRUD, per-user `asyncio.Lock`. |
| `modern_opalx_regsuite/remote.py` | Constructor gains `connection_name`, `gateway`, `gateway_key_path`, `env`. Cached `_gateway_conn`. New `_build_env_preamble()`. `run_command` no longer takes module-related kwargs. New `whoami()` for the test endpoint. Sanitized log headers. |
| `modern_opalx_regsuite/runner.py` | `run_pipeline` gains `connection`/`target_key_path`/`gateway_key_path`; drops `execution_host`/`execution_user`. `_run_regression_suite_remote` takes `connection` instead of `ac`. `_build_module_env` renamed to `_build_local_env` and takes an `EnvActivation`. `_validate_remote_config` deleted. All `RunMeta` writes use `connection_name`. Sanitized phase log lines. |
| `modern_opalx_regsuite/api/state.py` | `ActiveRun`/`QueuedRun` carry `connection_name` (public) plus in-memory `connection`/`target_key_path`/`gateway_key_path`. `resolve_machine_id` now takes `Optional[Connection]` and returns just `host` (no per-user component). |
| `modern_opalx_regsuite/api/coordinator.py` | Threads new fields through `run_pipeline_async` and `_start_queued_run`. |
| `modern_opalx_regsuite/api/deps.py` | New `require_user_paths` dependency. |
| `modern_opalx_regsuite/api/auth.py` | New `GET /api/auth/me` endpoint. |
| `modern_opalx_regsuite/api/keys.py` | Rewritten per-user. Atomic `O_CREAT | O_EXCL | O_WRONLY` key writes. DELETE returns 409 with dependent connections list. |
| `modern_opalx_regsuite/api/connections.py` | **NEW.** Full CRUD router + `/test` endpoint. |
| `modern_opalx_regsuite/api/runs.py` | `TriggerRequest` gains `connection_name`. `trigger_run` loads the calling user's connection, resolves key paths, and threads them through `acquire_run_slot` / `enqueue_run`. `CurrentRunStatus` and `QueuedRunInfo` expose `connection_name`. |
| `modern_opalx_regsuite/api/app.py` | Registers the new `connections` router. |
| `modern_opalx_regsuite/cli.py` | `user-add` calls `ensure_user_dir`. New `migrate-keys --user` command. |

**Frontend**

| File | Change |
|---|---|
| `frontend/src/api/runs.ts` | `TriggerRequest.connection_name?`, `CurrentRunStatus.connection_name?`. |
| `frontend/src/api/user.ts` | **NEW.** `getCurrentUser()`. |
| `frontend/src/api/connections.ts` | **NEW.** Full CRUD client + types + `LOCAL_CONNECTION` sentinel. |
| `frontend/src/components/ConnectionForm.tsx` | **NEW.** Create/edit form. |
| `frontend/src/pages/SettingsPage.tsx` | New Connections section. SSH-key delete handler decodes 409 dependent-connections response. |
| `frontend/src/pages/TriggerPage.tsx` | New Connection picker after the Run config select. |

**Docs**

| File | Change |
|---|---|
| `README.md` | New "Connections and remote execution" section replacing the old "Remote execution" section. Updated `config.toml` example to drop the removed fields and show the new `[arch_configs.env]` sub-table. New `migrate-keys` CLI entry. Sensitive-data isolation note. Updated data layout, run-queuing, and settings-page descriptions. |
| `CHANGELOG.md` | **NEW.** This document. |
