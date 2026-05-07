"""Run coordinator — manages concurrent pipeline execution.

Provides:
- A dedicated ``ThreadPoolExecutor`` so pipeline threads don't compete
  with the default executor used by FastAPI.
- Per-repo ``threading.Lock`` objects so concurrent pipelines serialise
  access to shared git repositories (local ``opalx_repo_root`` and
  ``regtests_repo_root``).
- A high-level ``run_pipeline_async()`` method that handles the full
  lifecycle: execute in thread, tail logs, release slot, dequeue next.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ..config import SuiteConfig
from ..runner import run_pipeline
from .state import (
    ActiveRun,
    QueuedRun,
    acquire_run_slot,
    release_run_slot,
)


class RunCoordinator:
    """Singleton that coordinates concurrent pipeline runs."""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pipeline",
        )
        # Per-repo locks: key is the resolved repo path (str), value is a
        # threading.Lock.  These are threading locks (not asyncio locks)
        # because the git operations happen inside run_in_executor threads.
        self._repo_locks: dict[str, threading.Lock] = {}
        self._repo_locks_guard = threading.Lock()

    # ── Repo locking ─────────────────────────────────────────────────────

    def get_repo_lock(self, repo_path: str) -> threading.Lock:
        """Return (or lazily create) a lock for *repo_path*."""
        with self._repo_locks_guard:
            if repo_path not in self._repo_locks:
                self._repo_locks[repo_path] = threading.Lock()
            return self._repo_locks[repo_path]

    def build_repo_locks(self, cfg: SuiteConfig) -> dict[str, threading.Lock]:
        """Build the repo-lock dict that ``run_pipeline()`` expects.

        Returns a dict mapping absolute repo path (str) to its lock.
        """
        locks: dict[str, threading.Lock] = {}
        locks[str(cfg.resolved_opalx_repo_root)] = self.get_repo_lock(
            str(cfg.resolved_opalx_repo_root)
        )
        locks[str(cfg.resolved_regtests_repo_root)] = self.get_repo_lock(
            str(cfg.resolved_regtests_repo_root)
        )
        return locks

    # ── Pipeline execution ───────────────────────────────────────────────

    async def run_pipeline_async(
        self,
        cfg: SuiteConfig,
        active: ActiveRun,
        skip_unit: bool,
        skip_regression: bool,
        clean_build: bool = False,
        custom_cmake_args: Optional[list[str]] = None,
    ) -> None:
        """Execute the pipeline in the dedicated thread pool.

        After the pipeline finishes (success or failure), releases the
        machine slot and auto-starts the next queued run if any.
        """
        loop = asyncio.get_running_loop()
        repo_locks = self.build_repo_locks(cfg)

        def _sync():
            return run_pipeline(
                cfg,
                branch=active.branch,
                arch=active.arch,
                run_id=active.run_id,
                skip_unit=skip_unit,
                skip_regression=skip_regression,
                clean_build=clean_build,
                custom_cmake_args=custom_cmake_args or active.custom_cmake_args,
                cancel_event=active.cancel_event,
                connection=active.connection,
                target_key_path=active.target_key_path,
                gateway_key_path=active.gateway_key_path,
                repo_locks=repo_locks,
                triggered_by=active.triggered_by,
                public=active.public,
                rerun_of=active.rerun_of,
                gateway_password=active.gateway_password,
                gateway_otp=active.gateway_otp,
            )

        tailer_task = asyncio.create_task(self._log_tailer(active))
        final_status = "failed"

        # Pipeline-level timeout watchdog: cancels the run after
        # max_pipeline_duration seconds to prevent zombie runs.
        timeout_handle = None
        timeout_seconds = (
            cfg.max_pipeline_duration if cfg.max_pipeline_duration > 0 else 0
        )
        if timeout_seconds:
            def _pipeline_timeout() -> None:
                active.cancel_event.set()
                if active.log_path:
                    try:
                        active.log_path.parent.mkdir(parents=True, exist_ok=True)
                        with active.log_path.open("a", encoding="utf-8") as f:
                            f.write(
                                f"\n[error] Pipeline timed out after "
                                f"{timeout_seconds}s — cancelling\n"
                            )
                    except Exception:
                        pass

            timeout_handle = loop.call_later(timeout_seconds, _pipeline_timeout)

        try:
            meta = await loop.run_in_executor(self._executor, _sync)
            final_status = meta.status
        except Exception as exc:
            if active.log_path:
                try:
                    active.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with active.log_path.open("a", encoding="utf-8") as f:
                        f.write(f"\n[error] Unhandled exception: {exc}\n")
                except Exception:
                    pass
        finally:
            if timeout_handle is not None:
                timeout_handle.cancel()
            tailer_task.cancel()
            try:
                await tailer_task
            except asyncio.CancelledError:
                pass

            # Release slot and auto-start next queued run.
            next_queued = await release_run_slot(active.machine_id, final_status)
            if next_queued is not None:
                await self._start_queued_run(next_queued)

    async def _start_queued_run(self, queued: QueuedRun) -> None:
        """Promote a queued run to active and start it."""
        next_active = await acquire_run_slot(
            run_id=queued.run_id,
            branch=queued.branch,
            arch=queued.arch,
            machine_id=queued.machine_id,
            connection_name=queued.connection_name,
            log_path=queued.log_path,
            triggered_by=queued.triggered_by,
            public=queued.public,
            rerun_of=queued.rerun_of,
            custom_cmake_args=queued.custom_cmake_args,
            connection=queued.connection,
            target_key_path=queued.target_key_path,
            gateway_key_path=queued.gateway_key_path,
            gateway_password=queued.gateway_password,
            gateway_otp=queued.gateway_otp,
        )
        if next_active is not None:
            next_active.cancel_event = queued.cancel_event
            asyncio.create_task(
                self.run_pipeline_async(
                    queued.cfg,  # type: ignore[arg-type]
                    next_active,
                    queued.skip_unit,
                    queued.skip_regression,
                    queued.clean_build,
                    queued.custom_cmake_args,
                )
            )

    # ── Log tailer ───────────────────────────────────────────────────────

    @staticmethod
    async def _log_tailer(active: ActiveRun) -> None:
        """Poll pipeline.log for new lines and push to SSE subscriber queues.

        Reads only newly appended bytes on each tick (seek to last offset)
        instead of re-reading the entire file, keeping the event-loop block
        proportional to new output rather than total log size.
        """
        import re

        _PHASE_RE = re.compile(r"^== PHASE: (\S+?) ==")
        line_no = 0
        byte_offset = 0
        leftovers = b""

        def _push_new_lines() -> None:
            nonlocal line_no, byte_offset, leftovers
            if not (active.log_path and active.log_path.exists()):
                return
            with active.log_path.open("rb") as f:
                f.seek(byte_offset)
                chunk = f.read()
            if not chunk:
                return
            byte_offset += len(chunk)
            data = leftovers + chunk
            parts = data.split(b"\n")
            leftovers = parts[-1]  # incomplete trailing line, buffer for next tick
            for raw in parts[:-1]:
                ln = raw.decode("utf-8", errors="replace")
                m = _PHASE_RE.match(ln)
                if m:
                    phase_val = m.group(1).split()[0]
                    active.phase = phase_val
                    event: dict = {
                        "type": "phase",
                        "phase": phase_val,
                        "id": line_no,
                    }
                else:
                    event = {"type": "log", "line": ln, "id": line_no}
                for q in list(active.sse_queues):
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        pass
                line_no += 1

        try:
            while True:
                _push_new_lines()
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            _push_new_lines()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Shutdown the thread pool (call during app teardown)."""
        self._executor.shutdown(wait=False)


# ── Module-level singleton ───────────────────────────────────────────────────

_coordinator: Optional[RunCoordinator] = None


def get_coordinator() -> RunCoordinator:
    """Return the singleton coordinator, creating it lazily if needed."""
    global _coordinator
    if _coordinator is None:
        _coordinator = RunCoordinator(max_workers=4)
    return _coordinator


def shutdown_coordinator() -> None:
    """Shutdown the coordinator (called during app teardown)."""
    global _coordinator
    if _coordinator is not None:
        _coordinator.shutdown()
        _coordinator = None
