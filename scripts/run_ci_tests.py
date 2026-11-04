"""Run the full offline suite and fail CI if any test was skipped."""

import sys

import pytest


class RequireAllTests:
    def __init__(self) -> None:
        self.skipped: list[str] = []

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.skipped:
            print(f"CI requires all tests: {len(self.skipped)} skipped.", file=sys.stderr)
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", *sys.argv[1:]], plugins=[RequireAllTests()]))
