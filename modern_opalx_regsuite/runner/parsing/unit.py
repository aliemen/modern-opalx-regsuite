"""Parse ctest output into a UnitTestsReport."""
from __future__ import annotations

import re

from ...data_model import UnitTestCase, UnitTestsReport


_CTEST_LINE = re.compile(
    r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s+\.+\s+"
    r"(Passed|\*{0,3}Failed\*{0,3}|Not Run)\s+([\d.]+)\s+sec",
)


def _parse_unit_output(output: str) -> UnitTestsReport:
    cases: list[UnitTestCase] = []
    for line in output.splitlines():
        m = _CTEST_LINE.match(line)
        if m:
            name = m.group(1)
            raw_status = m.group(2).strip("*")
            status = "passed" if raw_status == "Passed" else "failed"
            duration = float(m.group(3))
            cases.append(UnitTestCase(name=name, status=status, duration_seconds=duration))

    if not cases:
        status = "passed"
        if "failed" in output.lower() or "error" in output.lower():
            status = "failed"
        cases.append(UnitTestCase(name="unit-suite", status=status, output_snippet=output[-4000:]))

    return UnitTestsReport(tests=cases)
