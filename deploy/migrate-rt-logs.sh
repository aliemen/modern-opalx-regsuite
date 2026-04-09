#!/usr/bin/env bash
#
# One-shot migration: rename per-test regression log files from `.o` to
# `.log` and rewrite the matching `log_file` references in
# `regression-tests.json` so the dashboard's download links keep working.
#
# Why: editors and the browser used to download `<test>-RT.o` files which
# most editors won't auto-open. The runner now writes `<test>-RT.log`
# instead. Existing on-disk runs need to be migrated to the new naming.
#
# Idempotent: skips files that have already been migrated. Safe to re-run.
#
# Usage:
#   ./deploy/migrate-rt-logs.sh /path/to/data_root
#
# Or, while sitting in data_root:
#   ./deploy/migrate-rt-logs.sh .
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <data_root>" >&2
    exit 2
fi

DATA_ROOT="$1"
if [ ! -d "$DATA_ROOT" ]; then
    echo "Error: $DATA_ROOT is not a directory." >&2
    exit 2
fi

echo "Migrating regression log files in: $DATA_ROOT"

# 1) Rename every <test>-RT.o under runs/ to <test>-RT.log.
renamed=0
while IFS= read -r -d '' src; do
    dst="${src%.o}.log"
    if [ -e "$dst" ]; then
        echo "  skip (target exists): $src"
        continue
    fi
    mv -- "$src" "$dst"
    renamed=$((renamed + 1))
done < <(find "$DATA_ROOT" -type f -name '*-RT.o' -print0)
echo "Renamed $renamed file(s)."

# 2) Rewrite the `log_file` references in every regression-tests.json so the
#    download links in the dashboard point at the new filenames. We use a
#    short embedded Python script (rather than sed) so the JSON is parsed
#    and re-emitted as JSON — sed would be fragile against escaping.
patched=0
while IFS= read -r -d '' jsonf; do
    if python3 - "$jsonf" <<'PY'
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)

changed = False
for sim in data.get("simulations", []):
    log_file = sim.get("log_file")
    if isinstance(log_file, str) and log_file.endswith("-RT.o"):
        sim["log_file"] = log_file[:-2] + ".log"
        changed = True

if changed:
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    sys.exit(0)
sys.exit(2)
PY
    then
        patched=$((patched + 1))
    fi
done < <(find "$DATA_ROOT" -type f -name 'regression-tests.json' -print0)
echo "Patched $patched regression-tests.json file(s)."

echo "Done."
