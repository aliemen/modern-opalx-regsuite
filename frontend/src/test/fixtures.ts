import type { RunIndexEntry } from "../api/results";

/** A finished, passing index entry; override any field per test. */
export function makeRun(overrides: Partial<RunIndexEntry> = {}): RunIndexEntry {
  return {
    branch: "master",
    arch: "cpu-serial",
    run_id: "run-1",
    started_at: "2026-05-18T10:00:00Z",
    finished_at: "2026-05-18T10:01:00Z",
    status: "passed",
    triggered_by: "demo-user",
    regtest_branch: "master",
    connection_name: "local",
    unit_tests_total: 1,
    unit_tests_failed: 0,
    regression_total: 1,
    regression_passed: 1,
    regression_failed: 0,
    regression_broken: 0,
    archived: false,
    public: false,
    run_options: {
      skip_unit: false,
      skip_regression: false,
      clean_build: false,
      custom_cmake_args: [],
      mpi_ranks: 1,
      opalx_info_level: 2,
      slurm_resources: null,
    },
    rerun_of: null,
    ...overrides,
  };
}

/** In-memory localStorage, so tests do not depend on the jsdom storage backend. */
export function installLocalStorageMock(): void {
  const store = new Map<string, string>();
  const mock: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => store.get(key) ?? null,
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => void store.delete(key),
    setItem: (key, value) => void store.set(key, value),
  };
  Object.defineProperty(window, "localStorage", { value: mock, configurable: true });
  Object.defineProperty(globalThis, "localStorage", { value: mock, configurable: true });
}
